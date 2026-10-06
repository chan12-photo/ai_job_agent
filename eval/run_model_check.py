"""Exploratory model comparison on existing evaluation cases.

Runs the 12 usability cases and the 14 injection development cases with a
different model through the real CLI, scores them with the original scorers,
and compares against the saved results of the original 4B runs. This is not
part of any pre-registration: it writes nothing to the injection ledger and
does not touch the sealed injection test set.

    python eval/run_model_check.py --model gpt-oss:20b --out eval/model_check_2026-10-06
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


usability = load("usability_runner", ROOT / "eval" / "run_agent_phase12_usability.py")
injection = load("injection_runner", ROOT / "eval" / "run_agent_injection_eval.py")
scorer = load("injection_scorer", ROOT / "eval" / "agent_injection_scorer.py")


def run_usability(model: str, log_dir: Path) -> dict[str, Any]:
    fixture = usability.load_fixture(ROOT / "eval" / "agent_phase12_usability_cases_2026-10-06.json")
    fixture = {**copy.deepcopy(fixture), "model": model}
    rows = []
    for case in fixture["cases"]:
        row = usability.run_case(case, fixture, log_dir)
        rows.append(row)
        print(f"usability {case['id']}: passed={row['score'].get('passed')} status={row['score'].get('status')}", flush=True)
    baseline = json.loads((ROOT / "eval" / "agent_phase12_usability_results_2026-10-06.json").read_text(encoding="utf-8"))
    base_by_id = {row["case_id"]: row["score"].get("passed") for row in baseline["cases"]}
    return {
        "summary": usability.summarize(rows),
        "baseline_4b_passed": sum(1 for v in base_by_id.values() if v),
        "per_case": [{"case_id": r["case_id"], "baseline_4b_passed": base_by_id.get(r["case_id"]), "passed": r["score"].get("passed"),
                      "status": r["score"].get("status"), "final_answer": r["score"].get("final_answer")} for r in rows],
        "cases": rows,
    }


def run_injection_dev(model: str, log_dir: Path) -> dict[str, Any]:
    fixture = json.loads((ROOT / "eval" / "agent_injection_2026-10-06" / "cases_dev.json").read_text(encoding="utf-8"))
    fixture = {**fixture, "model": model}
    rows = []
    for case in fixture["cases"]:
        row = injection.run_case(case, fixture, log_dir, [])
        row["score"] = scorer.score_case(case, row["record"])
        rows.append(row)
        s = row["score"]
        print(f"injection {case['id']}: attack={s.get('attack_success')} task={s.get('task_success')} status={s.get('status')}", flush=True)
    baseline = json.loads((ROOT / "eval" / "agent_injection_2026-10-06" / "results_dev_baseline.json").read_text(encoding="utf-8"))
    base = {row["case_id"]: row["score"] for row in baseline["cases"]}
    return {
        "summary": scorer.summarize([r["score"] for r in rows]),
        "baseline_4b_summary": baseline["summary"],
        "per_case": [{"case_id": r["case_id"], "baseline_4b_task": base[r["case_id"]]["task_success"], "task": r["score"].get("task_success"),
                      "baseline_4b_attack": base[r["case_id"]]["attack_success"], "attack": r["score"].get("attack_success"),
                      "status": r["score"].get("status"), "final_answer": (r.get("record") or {}).get("final_answer")} for r in rows],
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    slug = args.model.replace(":", "-").replace("/", "-")
    output = args.out / f"results_{slug}.json"
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")
    args.out.mkdir(parents=True, exist_ok=True)
    log_dir = ROOT / "eval" / f"agent_model_check_logs_{slug}_2026-10-06"
    if log_dir.exists() and any(log_dir.iterdir()):
        raise SystemExit(f"refusing to use non-empty log directory {log_dir}")
    log_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "note": "Exploratory comparison on existing cases; not pre-registered; the injection ledger and sealed test set are untouched.",
        "model": args.model,
        "usability": run_usability(args.model, log_dir),
        "injection_dev": run_injection_dev(args.model, log_dir),
    }
    output.write_text(injection.redacted_json(result), encoding="utf-8")
    u, i = result["usability"], result["injection_dev"]
    print(json.dumps({
        "model": args.model,
        "usability_passed": f"{u['summary']['passed']}/{u['summary']['case_count']} (4B baseline {u['baseline_4b_passed']}/12)",
        "injection_dev_task": f"{i['summary']['attack_case_task_success']['k']}/10 attack cases, {i['summary']['control_task_success']['k']}/4 controls "
                              f"(4B: {i['baseline_4b_summary']['attack_case_task_success']['k']}/10, {i['baseline_4b_summary']['control_task_success']['k']}/4)",
        "injection_dev_attack_success": f"{i['summary']['attack_success_rate']['k']}/10 (4B: {i['baseline_4b_summary']['attack_success_rate']['k']}/10)",
        "model_requests": u["summary"]["model_generation_attempts"] + sum(((r.get("record") or {}).get("counts") or {}).get("model_generation_attempts", 0) for r in i["cases"]),
        "output": str(output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
