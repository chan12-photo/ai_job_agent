"""Phase 0.6-B native tool-calling generalization evaluation.

This evaluation reuses the Phase 0.5 native Ollama harness and the Phase 0.6-A
candidate prompt/tool descriptions.  It runs a separate synthetic fixture with
new filenames, search terms, and request phrasings.  Product data, OCR images,
and user documents are never opened.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from eval import run_agent_phase05_claude as base
from eval import run_agent_phase05_native as native
from eval import run_agent_phase06a_candidate as phase06a


EVALUATOR_VERSION = "phase06b-generalization-v1"
FIXTURE_VERSION_EXPECTED = "phase06b-generalization-fixture-v1"
DEFAULT_FIXTURE = Path("eval/agent_phase06b_generalization_cases_2026-10-05.json")
DEFAULT_PHASE06A_FULL = Path("eval/agent_phase06a_candidate_basic6_full_2026-10-05.json")
DEFAULT_PHASE06A_INTERMEDIATE = Path("eval/agent_phase06a_candidate_basic6_2026-10-05.json")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(data)


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("fixture_version") != FIXTURE_VERSION_EXPECTED:
        raise ValueError(f"unexpected fixture version: {data.get('fixture_version')}")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise ValueError("Phase 0.6-B fixture must define exactly 8 cases")
    ids = [case.get("id") for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Phase 0.6-B case IDs must be unique")
    if any(str(case_id).startswith("basic_") for case_id in ids):
        raise ValueError("Phase 0.6-B cases must not reuse basic6 IDs")
    return data


def create_workspace(root: Path, fixture: dict[str, Any]) -> None:
    for directory in fixture.get("directories", []):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for file_spec in fixture.get("files", []):
        path = root / file_spec["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file_spec["text"], encoding="utf-8")


def condition_definitions() -> list[dict[str, Any]]:
    baseline_tools = copy.deepcopy(native.NATIVE_TOOLS)
    candidate_tools = phase06a.candidate_tools()
    return [
        {
            "name": "baseline",
            "prompt": native.SYSTEM_PROMPT,
            "tools": baseline_tools,
            "evaluator_version": native.EVALUATOR_VERSION,
            "prompt_version": native.PROMPT_VERSION,
            "tool_contract_version": native.TOOL_CONTRACT_VERSION,
        },
        {
            "name": "candidate",
            "prompt": phase06a.CANDIDATE_SYSTEM_PROMPT,
            "tools": candidate_tools,
            "evaluator_version": phase06a.CANDIDATE_EVALUATOR_VERSION,
            "prompt_version": phase06a.CANDIDATE_PROMPT_VERSION,
            "tool_contract_version": phase06a.CANDIDATE_TOOL_CONTRACT_VERSION,
        },
    ]


def expected_arguments_match(case: dict[str, Any], normalized: dict[str, Any] | None) -> bool:
    if normalized is None:
        return False
    for key, expected_value in case.get("expected_args", {}).items():
        if normalized.get(key) != expected_value:
            return False
    return True


def evidence_verified(case: dict[str, Any], result: dict[str, Any] | None, normalized: dict[str, Any] | None) -> dict[str, Any]:
    if not expected_arguments_match(case, normalized):
        return {"passed": False, "reason": "tool arguments did not match requested path/query"}
    if not isinstance(result, dict) or result.get("ok") is not True:
        return {"passed": False, "reason": "tool did not return ok=true"}

    expected = case["expected_evidence"]
    kind = expected["type"]
    if kind == "list_entries":
        paths = {entry.get("path") for entry in result.get("entries", []) if isinstance(entry, dict)}
        missing = [item for item in expected["entries"] if item not in paths]
        return {"passed": not missing, "reason": None if not missing else f"missing entries: {missing}"}

    if kind == "read_contains":
        text = result.get("text", "")
        missing = [item for item in expected["contains"] if item not in text]
        return {"passed": not missing, "reason": None if not missing else f"missing text facts: {missing}"}

    if kind == "json_value":
        try:
            value = json.loads(result.get("text", "{}")).get(expected["key"])
        except json.JSONDecodeError:
            value = None
        ok = value == expected["value"]
        return {"passed": ok, "reason": None if ok else f"{expected['key']} was {value!r}"}

    if kind == "search_matches":
        if result.get("search_complete") is not True:
            return {"passed": False, "reason": "search was incomplete"}
        matches = result.get("matches", [])
        missing = []
        for wanted in expected["matches"]:
            found = any(
                isinstance(match, dict)
                and match.get("path") == wanted["path"]
                and wanted["text_contains"] in match.get("text", "")
                for match in matches
            )
            if not found:
                missing.append(wanted)
        return {"passed": not missing, "reason": None if not missing else f"missing matches: {missing}"}

    if kind == "search_no_matches":
        matches = result.get("matches", [])
        skipped = result.get("skipped", [])
        searched = result.get("searched_files", 0)
        ok = (
            matches == []
            and skipped == []
            and result.get("search_complete") is True
            and isinstance(searched, int)
            and searched >= expected["min_searched_files"]
        )
        reason = None if ok else f"expected complete no-match search; matches={matches}, skipped={skipped}, searched_files={searched}"
        return {"passed": ok, "reason": reason}

    return {"passed": False, "reason": f"unknown evidence type: {kind}"}


def final_answer_correct(case: dict[str, Any], answer: Any, evidence_ok: bool) -> dict[str, Any]:
    if not evidence_ok:
        return {"passed": False, "reason": "answer cannot be credited without verified tool evidence"}
    if not isinstance(answer, str):
        return {"passed": False, "reason": "no final answer"}

    criteria = case["answer_criteria"]
    lowered = answer.casefold()
    missing = [item for item in criteria.get("must_include", []) if item.casefold() not in lowered]
    missing_groups = [
        group
        for group in criteria.get("must_include_any", [])
        if not any(item.casefold() in lowered for item in group)
    ]
    forbidden = [item for item in criteria.get("must_exclude", []) if item.casefold() in lowered]
    if criteria.get("must_indicate_no_match"):
        no_match_markers = ["없", "찾지 못", "no match", "not found", "일치 항목"]
        if not any(marker.casefold() in lowered for marker in no_match_markers):
            missing.append("no-match indication")

    if missing or missing_groups or forbidden:
        parts = []
        if missing:
            parts.append(f"missing required answer facts: {missing}")
        if missing_groups:
            parts.append(f"missing one option from required groups: {missing_groups}")
        if forbidden:
            parts.append(f"answer included forbidden unsupported facts: {forbidden}")
        return {"passed": False, "reason": "; ".join(parts)}
    return {"passed": True, "reason": None}


def run_case(
    client: native.NativeTraceOllamaClient,
    root: Path,
    case: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    before_attempts = client.chat_attempts
    before_responses = client.chat_responses
    record: dict[str, Any] = {
        "case_id": case["id"],
        "user_request": case["request"],
        "expected_tool": case["expected_tool"],
        "expected_args": case["expected_args"],
        "expected_evidence": case["expected_evidence"],
        "answer_criteria": case["answer_criteria"],
        "initial": {},
        "native_tool_call_structure_passed": False,
        "selected_tool": None,
        "tool_call_original": None,
        "tool_arguments_original": None,
        "tool_arguments_original_raw": None,
        "selected_tool_correct": False,
        "tool_argument_contract_passed": False,
        "tool_argument_contract_reason": None,
        "tool_arguments_normalized": None,
        "policy_passed": None,
        "policy_reason": None,
        "execution_result": None,
        "requested_arguments_match": False,
        "evidence_verified": {"passed": False, "reason": "not evaluated"},
        "final": {},
        "final_reached": False,
        "final_answer_matches_evidence": {"passed": False, "reason": "not evaluated"},
        "second_tool_call": None,
        "second_tool_call_count": 0,
        "different_second_tool_call": False,
        "repeated_same_action": False,
        "ungrounded_final_answer": False,
        "error_misreported_as_no_match": False,
        "failure_reason": None,
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": case["request"]},
    ]
    try:
        first = client.complete_native(messages)
    except Exception as exc:
        record["failure_reason"] = f"initial request failed: {type(exc).__name__}: {exc}"
        record["failure_category"] = native._failure_category(record["failure_reason"])
        record["initial"] = {"native_tool_call_structure_passed": False, "error": record["failure_reason"]}
        record["model_generation_attempts"] = client.chat_attempts - before_attempts
        record["model_generation_responses"] = client.chat_responses - before_responses
        return record

    first_view = native.completion_view(first)
    parsed = native.parse_native_tool_call(first.get("message"))
    record["initial"] = {**first_view, "native_tool_call_structure_passed": parsed["passed"], "parse": parsed}
    record["native_tool_call_structure_passed"] = parsed["passed"]
    if not parsed["passed"]:
        content = first.get("message", {}).get("content") if isinstance(first.get("message"), dict) else None
        record["final"] = first_view
        record["final_reached"] = isinstance(content, str)
        record["ungrounded_final_answer"] = record["final_reached"]
        record["final_answer_matches_evidence"] = {"passed": False, "reason": "no native tool call; answer is ungrounded"}
        record["failure_reason"] = parsed["reason"]
        record["failure_category"] = "모델의 도구 선택·인자 생성 문제"
        record["model_generation_attempts"] = client.chat_attempts - before_attempts
        record["model_generation_responses"] = client.chat_responses - before_responses
        return record

    record["selected_tool"] = parsed["tool"]
    record["tool_call_original"] = parsed["call"]
    record["tool_arguments_original"] = parsed["original_args"]
    record["tool_arguments_original_raw"] = parsed.get("original_args_raw")
    record["selected_tool_correct"] = parsed["tool"] == case["expected_tool"]
    outcome = base.policy_and_execute(root, parsed["tool"], parsed["original_args"])
    record["tool_argument_contract_passed"] = outcome["tool_argument_contract_passed"]
    record["tool_argument_contract_reason"] = outcome["tool_argument_contract_reason"]
    record["tool_arguments_normalized"] = outcome["normalized_arguments"]
    record["policy_passed"] = outcome["policy_passed"]
    record["policy_reason"] = outcome["policy_reason"]
    record["execution_result"] = outcome["result"]
    record["requested_arguments_match"] = expected_arguments_match(case, outcome["normalized_arguments"])
    record["evidence_verified"] = evidence_verified(case, outcome["result"], outcome["normalized_arguments"])

    messages.append(copy.deepcopy(first["message"]))
    tool_content = json.dumps({
        "tool": parsed["tool"],
        "original_arguments": parsed["original_args"],
        "validation_and_execution": outcome,
    }, ensure_ascii=False)
    messages.append({"role": "tool", "tool_name": parsed["tool"], "content": tool_content})
    try:
        second = client.complete_native(messages)
    except Exception as exc:
        record["failure_reason"] = f"follow-up request failed: {type(exc).__name__}: {exc}"
        record["failure_category"] = native._failure_category(record["failure_reason"])
        record["final"] = {"native_tool_call_structure_passed": False, "error": record["failure_reason"]}
        record["model_generation_attempts"] = client.chat_attempts - before_attempts
        record["model_generation_responses"] = client.chat_responses - before_responses
        return record

    second_view = native.completion_view(second)
    second_parsed = native.parse_native_tool_call(second.get("message"))
    record["final"] = {**second_view, "native_tool_call_structure_passed": second_parsed["passed"], "parse": second_parsed}
    if second_parsed["passed"]:
        record["second_tool_call"] = {
            "tool": second_parsed["tool"],
            "arguments": second_parsed["original_args"],
        }
        record["second_tool_call_count"] = 1
        record["repeated_same_action"] = (
            second_parsed["tool"] == record["selected_tool"]
            and second_parsed["original_args"] == record["tool_arguments_original"]
        )
        record["different_second_tool_call"] = not record["repeated_same_action"]
        record["failure_reason"] = "model returned a second native tool call after execution"
        record["failure_category"] = "모델의 도구 선택·인자 생성 문제"
    else:
        final_message = second.get("message", {})
        content = final_message.get("content") if isinstance(final_message, dict) else None
        record["final_reached"] = isinstance(content, str)
        record["final_answer_matches_evidence"] = final_answer_correct(
            case, content, record["evidence_verified"]["passed"]
        )
        if isinstance(record["execution_result"], dict) and record["execution_result"].get("ok") is not True and isinstance(content, str):
            lowered = content.casefold()
            record["error_misreported_as_no_match"] = any(marker in lowered for marker in ["없", "not found", "no match"])
        if not record["final_answer_matches_evidence"]["passed"]:
            record["failure_reason"] = record["final_answer_matches_evidence"]["reason"]
            record["failure_category"] = "모델의 도구 선택·인자 생성 문제"

    record["model_generation_attempts"] = client.chat_attempts - before_attempts
    record["model_generation_responses"] = client.chat_responses - before_responses
    return record


def payload_audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures = []
    for row in records:
        initial = row.get("initial", {}).get("request_payload")
        final = row.get("final", {}).get("request_payload")
        if not isinstance(initial, dict):
            failures.append({"case_id": row["case_id"], "reason": "missing initial payload"})
            continue
        initial_roles = [msg.get("role") for msg in initial.get("messages", [])]
        initial_ok = len(initial.get("messages", [])) == 2 and initial_roles == ["system", "user"]
        if row.get("model_generation_attempts", 0) >= 2:
            final_roles = [msg.get("role") for msg in final.get("messages", [])] if isinstance(final, dict) else []
            final_ok = isinstance(final, dict) and len(final.get("messages", [])) == 4 and final_roles == ["system", "user", "assistant", "tool"]
        else:
            final_ok = True
        if not initial_ok or not final_ok:
            failures.append({
                "case_id": row["case_id"],
                "initial_roles": initial_roles,
                "final_roles": final_roles if row.get("model_generation_attempts", 0) >= 2 else None,
            })
    return {
        "passed": not failures,
        "method": "request payload snapshots are deep-copied inside NativeTraceOllamaClient.complete_native before later assistant/tool messages are appended; tests cover mutation at the send boundary",
        "failures": failures,
    }


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    def token_sum(key: str) -> int:
        total = 0
        for row in records:
            for phase in ("initial", "final"):
                value = row.get(phase, {}).get(key)
                if isinstance(value, int):
                    total += value
        return total

    def elapsed_sum() -> float:
        total = 0.0
        for row in records:
            for phase in ("initial", "final"):
                value = row.get(phase, {}).get("elapsed_ms")
                if isinstance(value, (int, float)):
                    total += float(value)
        return round(total, 3)

    total = len(records)
    return {
        "case_count": total,
        "native_tool_call_structure_passed": sum(row["native_tool_call_structure_passed"] for row in records),
        "selected_tool_correct": sum(row["selected_tool_correct"] for row in records),
        "original_argument_contract_passed": sum(row["tool_argument_contract_passed"] for row in records),
        "server_policy_passed": sum(row["policy_passed"] is True for row in records),
        "tool_execution_ok": sum(isinstance(row["execution_result"], dict) and row["execution_result"].get("ok") is True for row in records),
        "requested_arguments_match": sum(row["requested_arguments_match"] for row in records),
        "requested_evidence_verified": sum(row["evidence_verified"]["passed"] for row in records),
        "final_answer_reached": sum(row["final_reached"] for row in records),
        "final_answer_matches_evidence": sum(row["final_answer_matches_evidence"]["passed"] for row in records),
        "second_tool_call_count": sum(row["second_tool_call_count"] for row in records),
        "different_second_tool_call_count": sum(row["different_second_tool_call"] for row in records),
        "repeated_same_action_count": sum(row["repeated_same_action"] for row in records),
        "ungrounded_final_answer_count": sum(row["ungrounded_final_answer"] for row in records),
        "error_misreported_as_no_match_count": sum(row["error_misreported_as_no_match"] for row in records),
        "model_generation_attempts": sum(row.get("model_generation_attempts", 0) for row in records),
        "model_generation_responses": sum(row.get("model_generation_responses", 0) for row in records),
        "prompt_tokens": token_sum("prompt_tokens"),
        "output_tokens": token_sum("output_tokens"),
        "elapsed_ms": elapsed_sum(),
        "payload_audit": payload_audit(records),
    }


def run_condition(
    condition: dict[str, Any],
    fixture: dict[str, Any],
    model_metadata: dict[str, Any],
) -> dict[str, Any]:
    original_tools = native.NATIVE_TOOLS
    native.NATIVE_TOOLS = copy.deepcopy(condition["tools"])
    client = native.NativeTraceOllamaClient(base.MODEL)
    client.model_info = copy.deepcopy(model_metadata.get("_raw_model_info"))
    client.runtime_version = model_metadata.get("runtime_version")
    records = []
    try:
        for case in fixture["cases"]:
            with tempfile.TemporaryDirectory(prefix=f"phase06b-{condition['name']}-{case['id']}-") as temp:
                root = Path(temp) / "workspace"
                root.mkdir()
                create_workspace(root, fixture)
                records.append(run_case(client, root, case, condition["prompt"]))
    finally:
        native.NATIVE_TOOLS = original_tools
    return {
        "condition": condition["name"],
        "evaluator_version": condition["evaluator_version"],
        "prompt_version": condition["prompt_version"],
        "tool_contract_version": condition["tool_contract_version"],
        "prompt_sha256": sha256_text(condition["prompt"]),
        "tools_sha256": sha256_json(condition["tools"]),
        "summary": summarize_records(records),
        "cases": records,
    }


def phase06a_status(full_path: Path, intermediate_path: Path) -> dict[str, Any]:
    full = json.loads(full_path.read_text(encoding="utf-8"))
    full_ids = [case.get("case_id") for case in full.get("cases", [])]
    status = {
        "full_path": str(full_path),
        "full_summary": full.get("summary"),
        "full_case_count": len(full_ids),
        "full_unique_case_count": len(set(full_ids)),
        "full_case_ids": full_ids,
        "full_is_reference": len(full_ids) == 6 and len(set(full_ids)) == 6 and "_full_" in full_path.name,
        "intermediate_path": str(intermediate_path),
        "intermediate_note": "This artifact is preserved but is a mistaken single-case intermediate run, not the Phase 0.6-A full basic6 reference.",
    }
    if intermediate_path.exists():
        intermediate = json.loads(intermediate_path.read_text(encoding="utf-8"))
        status["intermediate_summary"] = intermediate.get("summary")
        status["intermediate_case_ids"] = [case.get("case_id") for case in intermediate.get("cases", [])]
    else:
        status["intermediate_summary"] = None
        status["intermediate_case_ids"] = []
    return status


def write_db(path: Path, output: dict[str, Any]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("""CREATE TABLE phase06b_requests (
            condition TEXT NOT NULL,
            case_id TEXT NOT NULL,
            user_request TEXT NOT NULL,
            raw_record TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (condition, case_id)
        )""")
        conn.execute("""CREATE TABLE phase06b_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        for key in [
            "evaluator_version",
            "fixture_version",
            "model_metadata",
            "condition_metadata",
            "generation_budget",
            "phase06a_status",
            "summaries",
        ]:
            conn.execute(
                "INSERT INTO phase06b_metadata VALUES (?, ?)",
                (key, json.dumps(output.get(key), ensure_ascii=False)),
            )
        for result in output["results"]:
            for row in result["cases"]:
                conn.execute(
                    "INSERT INTO phase06b_requests VALUES (?, ?, ?, ?, ?)",
                    (
                        result["condition"],
                        row["case_id"],
                        row["user_request"],
                        json.dumps(row, ensure_ascii=False),
                        base.utc_now(),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def verify_db(path: Path, expected_count: int) -> dict[str, Any]:
    conn = sqlite3.connect(path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM phase06b_requests").fetchone()[0]
        condition_count = conn.execute("SELECT COUNT(DISTINCT condition) FROM phase06b_requests").fetchone()[0]
        sample = conn.execute("SELECT condition, case_id, raw_record FROM phase06b_requests ORDER BY condition, case_id LIMIT 1").fetchone()
    finally:
        conn.close()
    sample_ok = sample is not None and json.loads(sample[2])["case_id"] == sample[1]
    return {"passed": count == expected_count and condition_count == 2 and sample_ok, "row_count": count, "condition_count": condition_count}


def write_report(path: Path, output: dict[str, Any]) -> None:
    by_condition = {result["condition"]: result for result in output["results"]}
    baseline = by_condition["baseline"]
    candidate = by_condition["candidate"]
    lines = [
        "# Phase 0.6-B generalization check",
        "",
        "This evaluation uses a synthetic fixture created for Phase 0.6-B. It is informed by the Phase 0.6-A failure mode and is not an independent external benchmark.",
        "",
        "## Fixed conditions",
        "",
        f"- Model: `{output['model_metadata'].get('model')}`",
        f"- Digest: `{output['model_metadata'].get('model_digest')}`",
        f"- Quantization: `{output['model_metadata'].get('quantization')}`",
        f"- Runtime: `{output['model_metadata'].get('runtime_version')}`",
        f"- Options: `{json.dumps(output['model_metadata'].get('options'), ensure_ascii=False)}`",
        f"- Baseline prompt hash: `{baseline['prompt_sha256']}`",
        f"- Baseline tools hash: `{baseline['tools_sha256']}`",
        f"- Candidate prompt hash: `{candidate['prompt_sha256']}`",
        f"- Candidate tools hash: `{candidate['tools_sha256']}`",
        f"- Phase 0.6-A full reference: `{output['phase06a_status']['full_path']}`",
        f"- Preserved non-reference intermediate: `{output['phase06a_status']['intermediate_path']}`",
        "",
        "## Summary",
        "",
        "| Metric | Baseline | Candidate |",
        "|---|---:|---:|",
    ]
    metric_labels = [
        ("selected_tool_correct", "Initial tool selected correctly"),
        ("requested_arguments_match", "Requested path/query matched"),
        ("requested_evidence_verified", "Requested evidence verified"),
        ("final_answer_matches_evidence", "Evidence-grounded final answer"),
        ("second_tool_call_count", "Second tool call"),
        ("repeated_same_action_count", "Same action repeated"),
        ("ungrounded_final_answer_count", "Ungrounded final answer"),
        ("error_misreported_as_no_match_count", "Tool error misreported as no match"),
        ("model_generation_attempts", "Generation attempts"),
        ("prompt_tokens", "Prompt tokens"),
        ("output_tokens", "Output tokens"),
        ("elapsed_ms", "Elapsed ms"),
    ]
    for key, label in metric_labels:
        lines.append(f"| {label} | {baseline['summary'].get(key)} | {candidate['summary'].get(key)} |")

    lines.extend([
        "",
        "## Case comparison",
        "",
        "| Case | Baseline tool(args) | Baseline final | Candidate tool(args) | Candidate final |",
        "|---|---|---:|---|---:|",
    ])
    baseline_cases = {row["case_id"]: row for row in baseline["cases"]}
    for row in candidate["cases"]:
        case_id = row["case_id"]
        base_row = baseline_cases[case_id]
        lines.append(
            f"| {case_id} | {base_row.get('selected_tool')} `{json.dumps(base_row.get('tool_arguments_original'), ensure_ascii=False)}` | "
            f"{'Y' if base_row['final_answer_matches_evidence']['passed'] else 'N'} | "
            f"{row.get('selected_tool')} `{json.dumps(row.get('tool_arguments_original'), ensure_ascii=False)}` | "
            f"{'Y' if row['final_answer_matches_evidence']['passed'] else 'N'} |"
        )

    lines.extend([
        "",
        "Full payload snapshots, raw server responses, original and normalized tool arguments, tool results, token counts, done reasons, and elapsed times are stored in the JSON and SQLite artifacts.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_output(args: argparse.Namespace) -> dict[str, Any]:
    fixture = load_fixture(args.fixture)
    conditions = condition_definitions()
    condition_metadata = {
        condition["name"]: {
            "evaluator_version": condition["evaluator_version"],
            "prompt_version": condition["prompt_version"],
            "tool_contract_version": condition["tool_contract_version"],
            "prompt_sha256": sha256_text(condition["prompt"]),
            "tools_sha256": sha256_json(condition["tools"]),
        }
        for condition in conditions
    }

    process = None
    reused = False
    try:
        process, reused = base.ensure_ollama()
        metadata_client = native.NativeTraceOllamaClient(base.MODEL)
        model_metadata = metadata_client.prepare_metadata()
        model_metadata["_raw_model_info"] = copy.deepcopy(metadata_client.model_info)
        results = [run_condition(condition, fixture, model_metadata) for condition in conditions]
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except Exception:
                process.kill()

    summaries = {result["condition"]: result["summary"] for result in results}
    total_attempts = sum(summary["model_generation_attempts"] for summary in summaries.values())
    output = {
        "evaluator_version": EVALUATOR_VERSION,
        "fixture_path": str(args.fixture),
        "fixture_version": fixture["fixture_version"],
        "fixture_note": fixture.get("note"),
        "fixture_hash": sha256_json(fixture),
        "protocol": "ollama-native-tools-message-tool_calls",
        "model_metadata": {key: value for key, value in model_metadata.items() if key != "_raw_model_info"},
        "ollama_server_reused": reused,
        "condition_metadata": condition_metadata,
        "phase06a_status": phase06a_status(args.phase06a_full, args.phase06a_intermediate),
        "results": results,
        "summaries": summaries,
        "generation_budget": {"max_attempts": 32, "actual_attempts": total_attempts},
        "synthetic_workspace_only": True,
        "created_at": base.utc_now(),
    }
    output["candidate_next_step_gate"] = {
        "required": {
            "candidate_evidence_grounded_answers": "8/8",
            "candidate_repeated_same_action_count": 0,
            "candidate_ungrounded_final_answer_count": 0,
            "candidate_payload_audit": True,
        },
        "passed": (
            summaries["candidate"]["final_answer_matches_evidence"] == 8
            and summaries["candidate"]["repeated_same_action_count"] == 0
            and summaries["candidate"]["ungrounded_final_answer_count"] == 0
            and summaries["candidate"]["payload_audit"]["passed"] is True
        ),
    }
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--phase06a-full", type=Path, default=DEFAULT_PHASE06A_FULL)
    parser.add_argument("--phase06a-intermediate", type=Path, default=DEFAULT_PHASE06A_INTERMEDIATE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    base.validate_output_paths(args.db, args.output, args.report)
    output = build_output(args)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_db(args.db, output)
    output["db_readback"] = verify_db(args.db, 16)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(args.report, output)
    print(json.dumps({
        "summaries": output["summaries"],
        "generation_budget": output["generation_budget"],
        "candidate_next_step_gate": output["candidate_next_step_gate"],
        "db_readback": output["db_readback"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
