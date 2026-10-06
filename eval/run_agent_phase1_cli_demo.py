"""Run the Phase 1 read-only CLI Agent against fixed synthetic demo cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


DEFAULT_CASES = Path("eval/agent_phase1_cli_demo_cases_2026-10-05.json")
SCORER_VERSION = "phase1-demo-scorer-v3"
CODE_FILES = ["local_agent/readonly_agent.py", "local_agent/__main__.py", "local_agent/llm.py", "eval/run_agent_phase1_cli_demo.py"]


def code_manifest() -> dict[str, str | None]:
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() if Path(name).is_file() else None for name in CODE_FILES}


def load_cases(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("fixture_version") != "phase1-readonly-cli-demo-v1":
        raise ValueError("unexpected demo fixture version")
    if len(data.get("cases", [])) != 6:
        raise ValueError("demo fixture must contain exactly 6 cases")
    ids = [case["id"] for case in data["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("demo case IDs must be unique")
    return data


def validate_output_paths(*paths: Path) -> None:
    resolved = [path.resolve(strict=False) for path in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("output paths must be different")
    for path in paths:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing output: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)


def tool_sequence(record: dict[str, Any]) -> list[str]:
    return [
        step["tool"]
        for step in record.get("steps", [])
        if step.get("kind") == "tool" and step.get("executed") is not False
    ]


def executed_tool_steps(record: dict[str, Any]) -> list[dict[str, Any]]:
    # Phase 1 (2026-10-05) records have no "executed" field because every
    # recorded tool step ran; only an explicit False means "not executed".
    return [
        step for step in record.get("steps", [])
        if step.get("kind") == "tool" and step.get("executed") is not False
    ]


def final_answer(record: dict[str, Any]) -> str:
    return record.get("final_answer") or ""


def has_text(value: str, needle: str) -> bool:
    return needle.casefold() in value.casefold()


def executed_search_matches_args(steps: list[dict[str, Any]], query: str, path: str) -> bool:
    for step in steps:
        args = step.get("original_arguments") or {}
        if step.get("tool") == "search_text" and args.get("query") == query and isinstance(args.get("path"), str) and os.path.normpath(args["path"]) == path:
            return True
    return False


def boolean_answer_state(answer: str, expected: str, opposite: str) -> bool | None:
    """True/False when the answer is unambiguous; None when both values appear.

    A sentence such as "true가 아니라 false" mentions both values, so string
    rules cannot decide it; it is left for manual review instead of being
    counted as either correct or wrong.
    """
    has_expected = has_text(answer, expected)
    has_opposite = has_text(answer, opposite)
    if has_expected and not has_opposite:
        return True
    if has_expected and has_opposite:
        return None
    return False


def facts_ok(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"passed": False, "checks": [], "missing": case.get("expected_facts", [])}
    checks = []
    answer = final_answer(record)
    evidence = record.get("evidence", [])
    steps = executed_tool_steps(record)
    case_id = case["id"]

    def add(name: str, passed: bool | None, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    if case_id == "demo_01_list_root":
        entries = []
        for item in evidence:
            if item.get("tool") == "list_files":
                entries.extend(entry.get("path") for entry in item.get("entries", []))
        for expected in case["expected_facts"]:
            add(f"entry:{expected}", expected in entries, f"entries={entries}")
    elif case_id == "demo_02_read_value":
        text = "\n".join(item.get("text_preview", "") for item in evidence if item.get("tool") == "read_file")
        add("read_enabled_false", '"enabled": false' in text or '"enabled":false' in text.replace(" ", ""), text)
        add("answer_says_false", boolean_answer_state(answer, "false", "true"), answer)
    elif case_id == "demo_03_search_file":
        matches = []
        for item in evidence:
            if item.get("tool") == "search_text":
                matches.extend(item.get("matches", []))
        add("search_args_query_and_file", executed_search_matches_args(steps, "CODE_RED", "src/report.py"), str([s.get("original_arguments") for s in steps]))
        add("search_found_code_red_in_file", any(match.get("path") == "src/report.py" and "CODE_RED" in match.get("text", "") for match in matches), str(matches))
        add("answer_mentions_code_red", has_text(answer, "CODE_RED"), answer)
    elif case_id == "demo_04_search_no_match":
        search_items = [item for item in evidence if item.get("tool") == "search_text"]
        add("search_args_query_and_dir", executed_search_matches_args(steps, "MISSING_NEEDLE_42", "docs"), str([s.get("original_arguments") for s in steps]))
        add("search_completed_with_no_matches", any(item.get("matches") == [] and item.get("search_complete") is True for item in search_items), str(search_items))
        add("answer_reports_no_match", ("없" in answer or has_text(answer, "no match")) and not has_text(answer, "찾았습니다"), answer)
    elif case_id == "demo_05_list_then_read":
        listed = any(
            item.get("tool") == "list_files"
            and any(entry.get("path") == "reports/quarter_summary.md" for entry in item.get("entries", []))
            for item in evidence
        )
        read_text = "\n".join(item.get("text_preview", "") for item in evidence if item.get("tool") == "read_file")
        add("listed_report_file", listed, str(evidence))
        add("read_quarter_review", "Quarter Review" in read_text, read_text)
        add("answer_quarter_review", "Quarter Review" in answer, answer)
    elif case_id == "demo_06_read_two_files":
        read_paths = [item.get("path") for item in evidence if item.get("tool") == "read_file"]
        read_text = "\n".join(item.get("text_preview", "") for item in evidence if item.get("tool") == "read_file")
        add("read_both_files", read_paths == ["docs/alpha.md", "docs/beta.md"], str(read_paths))
        add("evidence_has_common_project", read_text.count("Project Helio") >= 2, read_text)
        add("answer_common_project", "Project Helio" in answer, answer)
    else:
        for fact in case.get("expected_facts", []):
            add(f"manual_fact:{fact}", False, "no automatic checker for this case")

    if any(item["passed"] is False for item in checks):
        passed: bool | None = False
    elif any(item["passed"] is None for item in checks):
        passed = None
    else:
        passed = True
    return {
        "passed": passed,
        "checks": checks,
        "missing": [item["name"] for item in checks if item["passed"] is False],
        "manual_review": [item["name"] for item in checks if item["passed"] is None],
        "tool_argument_summary": [
            {"tool": step.get("tool"), "arguments": step.get("original_arguments")}
            for step in steps
        ],
    }


def run_case(case: dict[str, Any], fixture: dict[str, Any], log_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "local_agent",
        "--workspace",
        fixture["workspace"],
        "--question",
        case["request"],
        "--model",
        fixture["model"],
        "--log-dir",
        str(log_dir),
        "--max-model-calls",
        str(fixture["max_model_calls_per_case"]),
        "--max-tool-calls",
        str(fixture["max_tool_calls_per_case"]),
        "--json",
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=220)
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        return {
            "case_id": case["id"],
            "request": case["request"],
            "expected_tools": case["expected_tools"],
            "actual_tools": [],
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "stdout_json_parse_error": "subprocess timed out",
            "record": None,
            "facts_check": {"passed": False, "checks": [], "missing": case.get("expected_facts", [])},
            "passed": False,
            "elapsed_ms": elapsed_ms,
            "runner_error": "subprocess_timeout",
        }
    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    record = None
    parse_error = None
    try:
        record = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        parse_error = str(exc)
    actual_tools = tool_sequence(record) if isinstance(record, dict) else []
    facts = facts_ok(case, record) if isinstance(record, dict) else {"passed": False, "checks": [], "missing": case.get("expected_facts", [])}
    passed = (
        proc.returncode == 0
        and isinstance(record, dict)
        and record.get("status") == "completed"
        and actual_tools == case["expected_tools"]
        and facts["passed"] is True
    )
    return {
        "case_id": case["id"],
        "request": case["request"],
        "expected_tools": case["expected_tools"],
        "actual_tools": actual_tools,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "stdout_json_parse_error": parse_error,
        "record": record,
        "facts_check": facts,
        "passed": passed,
        "elapsed_ms": elapsed_ms,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def count(key: str) -> int:
        return sum(1 for row in rows if row.get(key))

    total_model_attempts = 0
    total_model_responses = 0
    total_prompt_tokens = 0
    total_output_tokens = 0
    total_elapsed = 0.0
    for row in rows:
        counts = (row.get("record") or {}).get("counts", {})
        total_model_attempts += counts.get("model_generation_attempts", 0)
        total_model_responses += counts.get("model_generation_responses", 0)
        total_prompt_tokens += counts.get("prompt_tokens", 0)
        total_output_tokens += counts.get("output_tokens", 0)
        total_elapsed += counts.get("elapsed_ms", 0)
    return {
        "case_count": len(rows),
        "passed": count("passed"),
        "completed": sum(1 for row in rows if (row.get("record") or {}).get("status") == "completed"),
        "tool_sequence_matched": sum(1 for row in rows if row.get("actual_tools") == row.get("expected_tools")),
        "facts_matched": sum(1 for row in rows if row.get("facts_check", {}).get("passed") is True),
        "facts_manual_review": sum(1 for row in rows if row.get("facts_check", {}).get("passed") is None and row.get("facts_check", {}).get("checks")),
        "model_generation_attempts": total_model_attempts,
        "model_generation_responses": total_model_responses,
        "prompt_tokens": total_prompt_tokens,
        "output_tokens": total_output_tokens,
        "agent_elapsed_ms": round(total_elapsed, 3),
    }


def write_report(path: Path, output: dict[str, Any]) -> None:
    lines = [
        "# Phase 1 read-only CLI Agent demo",
        "",
        f"- Fixture: `{output['fixture_path']}`",
        f"- Workspace: `{output['workspace']}`",
        f"- Model: `{output.get('model')}`",
        f"- Log directory: `{output['log_dir']}`",
        "",
        "## Summary",
        "",
        f"- Passed: `{output['summary']['passed']}/{output['summary']['case_count']}`",
        f"- Model attempts/responses: `{output['summary']['model_generation_attempts']} / {output['summary']['model_generation_responses']}`",
        f"- Prompt/output tokens: `{output['summary']['prompt_tokens']} / {output['summary']['output_tokens']}`",
        f"- Agent elapsed ms: `{output['summary']['agent_elapsed_ms']}`",
        "",
        "## Cases",
        "",
        "| Case | Expected tools | Actual tools | Status | Passed | Log |",
        "|---|---|---|---|---:|---|",
    ]
    for row in output["cases"]:
        record = row.get("record") or {}
        lines.append(
            f"| {row['case_id']} | `{row['expected_tools']}` | `{row['actual_tools']}` | "
            f"{record.get('status')} | {'Y' if row['passed'] else 'N'} | `{record.get('log_path')}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    validate_output_paths(args.output, args.report)
    if args.log_dir.exists() and any(args.log_dir.iterdir()):
        raise FileExistsError(f"refusing to use non-empty log directory: {args.log_dir}")
    args.log_dir.mkdir(parents=True, exist_ok=True)

    fixture = load_cases(args.cases)
    rows = []

    def current_output() -> dict[str, Any]:
        return {
            "fixture_path": str(args.cases),
            "fixture_version": fixture["fixture_version"],
            "workspace": fixture["workspace"],
            "model": fixture["model"],
            "log_dir": str(args.log_dir),
            "scorer_version": SCORER_VERSION,
            "code_sha256": code_manifest(),
            "cases": rows,
            "summary": summarize(rows),
        }

    for case in fixture["cases"]:
        rows.append(run_case(case, fixture, args.log_dir))
        partial = current_output()
        args.output.write_text(json.dumps(partial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    output = {
        "fixture_path": str(args.cases),
        "fixture_version": fixture["fixture_version"],
        "workspace": fixture["workspace"],
        "model": fixture["model"],
        "log_dir": str(args.log_dir),
        "scorer_version": SCORER_VERSION,
        "code_sha256": code_manifest(),
        "cases": rows,
        "summary": summarize(rows),
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(args.report, output)
    print(json.dumps({"summary": output["summary"], "output": str(args.output), "report": str(args.report)}, ensure_ascii=False, indent=2))
    return 0 if output["summary"]["passed"] == output["summary"]["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
