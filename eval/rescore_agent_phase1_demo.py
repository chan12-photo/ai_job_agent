"""Offline re-score of saved Phase 1 demo results with the current demo scorer.

Reads saved result JSON files only (no model calls) and writes a new output
file next to them.  Input files are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parent / "run_agent_phase1_cli_demo.py"
spec = importlib.util.spec_from_file_location("phase1_demo_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def rescore_file(path: Path, cases: dict[str, dict]) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in data.get("cases", []):
        case = cases.get(row["case_id"])
        record = row.get("record")
        if case is None or not isinstance(record, dict):
            rows.append({"case_id": row["case_id"], "old_passed": row.get("passed"), "new_passed": None, "note": "missing case or record; unverified"})
            continue
        facts = runner.facts_ok(case, record)
        actual_tools = runner.tool_sequence(record)
        new_passed = (
            row.get("returncode") == 0
            and record.get("status") == "completed"
            and actual_tools == case["expected_tools"]
            and facts["passed"] is True
        )
        rows.append({
            "case_id": row["case_id"],
            "old_passed": row.get("passed"),
            "old_facts_passed": (row.get("facts_check") or {}).get("passed"),
            "new_passed": new_passed,
            "new_facts_passed": facts["passed"],
            "new_missing": facts["missing"],
            "new_manual_review": facts["manual_review"],
            "status": record.get("status"),
            "actual_tools": actual_tools,
            "tool_arguments": facts.get("tool_argument_summary"),
        })
    return {
        "path": str(path),
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "input_scorer_version": data.get("scorer_version", "phase1-demo-scorer-v1 (field absent)"),
        "old_summary": data.get("summary"),
        "new_summary": {
            "case_count": len(rows),
            "passed": sum(1 for r in rows if r.get("new_passed") is True),
            "facts_matched": sum(1 for r in rows if r.get("new_facts_passed") is True),
            "facts_manual_review": sum(1 for r in rows if r.get("new_facts_passed") is None and r.get("note") is None),
            "unverified": sum(1 for r in rows if r.get("note")),
        },
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=runner.DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("inputs", type=Path, nargs="+")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {args.output}")
    fixture = runner.load_cases(args.cases)
    cases = {case["id"]: case for case in fixture["cases"]}
    output = {
        "rescore_version": f"{runner.SCORER_VERSION}-offline",
        "note": "Offline re-score of saved synthetic Phase 1 demo outputs. Inputs are preserved; this is not a new model run.",
        "scorer_sha256": hashlib.sha256(RUNNER_PATH.read_bytes()).hexdigest(),
        "inputs": [rescore_file(path, cases) for path in args.inputs],
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{"path": item["path"], "old": (item["old_summary"] or {}).get("passed"), "new": item["new_summary"]} for item in output["inputs"]], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
