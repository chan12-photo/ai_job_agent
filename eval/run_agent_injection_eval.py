"""Runner for the pre-registered indirect prompt injection evaluation.

Enforced rules (see eval/agent_injection_2026-10-06/PREREGISTRATION.md):
- cases, scorer, and workspace must match the hashes in prereg_manifest.json;
- every run is recorded in ledger.json and the total model request budget is
  capped, counting a run's worst case until it finishes;
- the test set may run only twice, labelled "baseline" then "final", and the
  runner prints only aggregate numbers for it;
- outputs are never overwritten and local absolute paths are redacted.

    python eval/run_agent_injection_eval.py --set dev --label baseline
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PREREG_DIR = ROOT / "eval" / "agent_injection_2026-10-06"
MANIFEST = PREREG_DIR / "prereg_manifest.json"
LEDGER = PREREG_DIR / "ledger.json"
SCORER_PATH = ROOT / "eval" / "agent_injection_scorer.py"
TOTAL_REQUEST_CAP = 250
TEST_LABELS = ("baseline", "final")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scorer = load_module("agent_injection_scorer", SCORER_PATH)
redactor = load_module("redact_local_paths", ROOT / "scripts" / "redact_local_paths.py")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def current_hashes() -> dict[str, str]:
    workspace = ROOT / json.loads((PREREG_DIR / "cases_dev.json").read_text(encoding="utf-8"))["workspace"]
    return {
        "cases_dev.json": sha256_file(PREREG_DIR / "cases_dev.json"),
        "cases_test.json": sha256_file(PREREG_DIR / "cases_test.json"),
        "PREREGISTRATION.md": sha256_file(PREREG_DIR / "PREREGISTRATION.md"),
        "eval/agent_injection_scorer.py": sha256_file(SCORER_PATH),
        "workspace_tree": tree_sha256(workspace),
    }


def write_manifest() -> None:
    if MANIFEST.exists():
        raise FileExistsError(f"refusing to overwrite pre-registration manifest: {MANIFEST}")
    MANIFEST.write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha256": current_hashes()}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST}")


def verify_manifest() -> None:
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["sha256"]
    actual = current_hashes()
    changed = [name for name in expected if expected[name] != actual.get(name)]
    if changed:
        raise SystemExit(f"pre-registered files changed since registration: {changed}")


def load_ledger() -> list[dict[str, Any]]:
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else []


def save_ledger(entries: list[dict[str, Any]]) -> None:
    LEDGER.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def requests_used(entries: list[dict[str, Any]]) -> int:
    return sum(entry["model_requests"] if entry.get("status") == "finished" else entry["reserved_requests"] for entry in entries)


def check_rules(entries: list[dict[str, Any]], case_set: str, label: str, worst_case: int) -> None:
    if any(entry["set"] == case_set and entry["label"] == label for entry in entries):
        raise SystemExit(f"run {case_set}/{label} already exists in the ledger")
    if case_set == "test":
        if label not in TEST_LABELS:
            raise SystemExit(f"the test set only allows labels {TEST_LABELS}")
        if label == "final" and not any(e["set"] == "test" and e["label"] == "baseline" and e.get("status") == "finished" for e in entries):
            raise SystemExit("the final test run requires a finished baseline test run")
    used = requests_used(entries)
    # Keep the worst case of the required test runs (baseline, final) reserved
    # so that development runs can never consume the budget they need.
    test_fixture = json.loads((PREREG_DIR / "cases_test.json").read_text(encoding="utf-8"))
    test_worst = len(test_fixture["cases"]) * test_fixture["max_model_calls_per_case"]
    pending = [lab for lab in TEST_LABELS if not any(e["set"] == "test" and e["label"] == lab for e in entries)]
    reserved = test_worst * len([lab for lab in pending if not (case_set == "test" and lab == label)])
    if used + worst_case + reserved > TOTAL_REQUEST_CAP:
        raise SystemExit(f"budget: {used} used + {worst_case} worst case + {reserved} reserved for test runs exceeds cap {TOTAL_REQUEST_CAP}")


def run_case(case: dict[str, Any], fixture: dict[str, Any], log_dir: Path, agent_args: list[str]) -> dict[str, Any]:
    command = [
        sys.executable, "-m", "job_agent", "agent-read",
        "--workspace", str(ROOT / fixture["workspace"]),
        "--question", case["request"],
        "--model", fixture["model"],
        "--log-dir", str(log_dir),
        "--max-model-calls", str(fixture["max_model_calls_per_case"]),
        "--max-tool-calls", str(fixture["max_tool_calls_per_case"]),
        "--json", *agent_args,
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=240, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return {"case_id": case["id"], "record": None, "runner_error": "subprocess_timeout", "wall_ms": round((time.monotonic() - started) * 1000, 1)}
    try:
        record = json.loads(proc.stdout)
    except json.JSONDecodeError:
        record = None
    return {"case_id": case["id"], "returncode": proc.returncode, "stderr": proc.stderr[-2000:], "record": record,
            "wall_ms": round((time.monotonic() - started) * 1000, 1)}


def redacted_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    redacted, _counts = redactor.redact(text, str(ROOT), str(Path.home()))
    return redacted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="case_set", choices=["dev", "test"])
    parser.add_argument("--label")
    parser.add_argument("--agent-arg", action="append", default=[], help="extra argument passed to agent-read (e.g. a prompt profile)")
    parser.add_argument("--write-manifest", action="store_true", help="register the current cases, scorer, and workspace (once)")
    args = parser.parse_args(argv)
    if args.write_manifest:
        write_manifest()
        return 0
    if not args.case_set or not args.label:
        parser.error("--set and --label are required for a run")
    verify_manifest()

    fixture = json.loads((PREREG_DIR / f"cases_{args.case_set}.json").read_text(encoding="utf-8"))
    cases = fixture["cases"]
    worst_case = len(cases) * fixture["max_model_calls_per_case"]
    entries = load_ledger()
    check_rules(entries, args.case_set, args.label, worst_case)
    output = PREREG_DIR / f"results_{args.case_set}_{args.label}.json"
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")
    log_dir = ROOT / "eval" / f"agent_injection_logs_{args.case_set}_{args.label}_2026-10-06"
    if log_dir.exists() and any(log_dir.iterdir()):
        raise SystemExit(f"refusing to use non-empty log directory {log_dir}")

    entry = {
        "set": args.case_set, "label": args.label, "status": "running", "agent_args": args.agent_arg,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "reserved_requests": worst_case,
        "runtime_sha256": sha256_file(ROOT / "job_agent" / "readonly_agent.py"),
    }
    entries.append(entry)
    save_ledger(entries)

    rows = []
    for case in cases:
        row = run_case(case, fixture, log_dir, args.agent_arg)
        row["score"] = scorer.score_case(case, row["record"])
        rows.append(row)
        if args.case_set == "dev":
            s = row["score"]
            print(f"{case['id']} {case['kind']:7s} attack={s.get('attack_success')!s:5s} task={s.get('task_success')!s:5s} status={s.get('status')}", flush=True)
        else:
            print(f"test case {len(rows)}/{len(cases)} done", flush=True)

    summary = scorer.summarize([row["score"] for row in rows])
    used = sum(((row.get("record") or {}).get("counts") or {}).get("model_generation_attempts", 0) for row in rows)
    result = {
        "set": args.case_set, "label": args.label, "agent_args": args.agent_arg,
        "prereg_manifest": json.loads(MANIFEST.read_text(encoding="utf-8")),
        "runtime_sha256": entry["runtime_sha256"], "model_requests": used,
        "summary": summary, "cases": rows,
    }
    output.write_text(redacted_json(result), encoding="utf-8")
    entry.update({"status": "finished", "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model_requests": used})
    save_ledger(entries)
    print(json.dumps({"set": args.case_set, "label": args.label, "model_requests": used, "budget_used_total": requests_used(entries),
                      "attack_success_rate": summary["attack_success_rate"], "attack_case_task_success": summary["attack_case_task_success"],
                      "control_task_success": summary["control_task_success"], "hijack_attempt_rate": summary["hijack_attempt_rate"],
                      "statuses": summary["statuses"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
