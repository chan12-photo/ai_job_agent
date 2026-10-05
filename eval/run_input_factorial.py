"""Eight first-response-only local matching calls for two synthetic M1 cases."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.request

from job_agent import llm, match


CASES_PATH = Path(__file__).with_name("match_cases.json")
CASE_IDS = ("source_conflict", "two_sources_support")
MODEL = "qwen3:4b-instruct-2507-q4_K_M"
EXPECTED_DIGEST = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"


def conditions():
    cases = {case["id"]: case for case in json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]}
    for case_id in CASE_IDS:
        case = cases[case_id]
        for order in ("original", "reversed"):
            for markers in ("shared", "separate"):
                indexes = (1, 2) if order == "original" else (2, 1)
                candidates = [{
                    "evidence_id": index,
                    "version_id": 1 if markers == "shared" else index,
                    "title": "가상 경력" if markers == "shared" else f"가상 경력 {index}",
                    "text": case["candidates"][index - 1],
                } for index in indexes]
                batch = [{"requirement_id": "r1", "kind": "required",
                          "requirement_quote": case["requirement_quote"],
                          "candidates": candidates}]
                yield case, order, markers, batch


def save(path, report):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(output):
    if output.exists():
        raise FileExistsError(f"기존 평가 결과를 덮어쓰지 않습니다: {output}")
    if match.PROMPT_VERSION != "match-v5":
        raise ValueError("이 실험은 기존 match-v5 프롬프트에만 적용합니다")
    client = llm.OllamaClient(MODEL, timeout=120)
    model_info = next((item for item in client.local_models() if item.get("name") == MODEL), None)
    if model_info is None or model_info.get("digest") != EXPECTED_DIGEST:
        raise ValueError("기존 평가와 같은 로컬 모델 digest를 확인할 수 없습니다")
    runtime = client._request("/api/version").get("version")
    if runtime != "0.34.4":
        raise ValueError("기존 평가와 같은 Ollama 런타임 버전이 아닙니다")

    report = {
        "notice": "가상 평가 자료만 사용했습니다. 제품의 저장 문서·분석·프롬프트는 변경하지 않았습니다.",
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL, "model_digest": EXPECTED_DIGEST,
        "quantization": model_info.get("details", {}).get("quantization_level"),
        "runtime_version": runtime, "prompt_version": match.PROMPT_VERSION,
        "request_url": llm.BASE_URL + "/api/chat", "timeout_seconds": client.timeout,
        "options": dict(llm.OPTIONS), "max_first_match_calls": 8,
        "cases_path": str(CASES_PATH), "calls": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    for index, (case, order, markers, batch) in enumerate(conditions(), 1):
        payload = {"model": MODEL, "messages": match.messages(batch),
                   "stream": False, "think": False, "format": match.SCHEMA,
                   "options": dict(llm.OPTIONS)}
        request_json = json.dumps(payload, ensure_ascii=False)
        record = {
            "call_index": index, "case_id": case["id"],
            "requirement_quote": case["requirement_quote"],
            "source_texts": case["candidates"], "expected": case["expected"],
            "candidate_order": order, "document_markers": markers,
            "historical_workflow_layout": (
                (case["id"] == "source_conflict" and order == "reversed" and markers == "separate") or
                (case["id"] == "two_sources_support" and order == "original" and markers == "separate")),
            "attempt": 1, "retry_attempts": 0, "recovery_attempts": 0,
            "request_json": request_json,
            "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        request = urllib.request.Request(
            llm.BASE_URL + "/api/chat", data=request_json.encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST")
        started = time.monotonic()
        try:
            with client.opener.open(request, timeout=client.timeout) as response:
                if response.url != llm.BASE_URL + "/api/chat":
                    raise llm.LocalModelError("로컬 서버의 redirect를 허용하지 않습니다")
                raw_bytes = response.read(2 * 1024 * 1024 + 1)
            if len(raw_bytes) > 2 * 1024 * 1024:
                raise llm.LocalModelError("로컬 모델 응답이 너무 큽니다")
            raw_text = raw_bytes.decode("utf-8")
            raw = json.loads(raw_text)
            record["raw_response_text"] = raw_text
            record["server_done"] = raw.get("done")
            record["server_done_reason"] = raw.get("done_reason")
            record["server_done_reason_present"] = "done_reason" in raw
            content = raw.get("message", {}).get("content")
            try:
                proposal = match.validate(content, batch)["r1"]
                record["proposal"] = proposal
                record["assessment"] = proposal["assessment"]
                record["selected_evidence_ids"] = proposal["evidence_ids"]
                record["matches_expected"] = proposal["assessment"] in case["expected"]
            except (match.InvalidMatch, KeyError, TypeError) as exc:
                record["validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
                record["matches_expected"] = False
        except (OSError, ValueError, llm.LocalModelError) as exc:
            record["request_error"] = {"type": type(exc).__name__, "message": str(exc)}
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["calls"].append(record)
        save(output, report)
        print(f"{index}/8 {case['id']} {order}/{markers}: "
              f"{record.get('assessment', record.get('request_error', record.get('validation_error')))}",
              flush=True)
        if "request_error" in record:
            break
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output)
    print(f"first matching calls: {len(report['calls'])}/8; result: {args.output}")


if __name__ == "__main__":
    main()
