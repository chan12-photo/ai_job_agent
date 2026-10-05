"""Compare one match prompt candidate on fixed, provenance-preserving synthetic inputs."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.request

from job_agent import llm, match, retrieval


ROOT = Path(__file__).parent
MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DIGEST = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
FACTORIAL = ROOT / "phase4_order_markers_factorial_2026-09-30.json"
CANDIDATE = ROOT / "match_v8_candidate.txt"
SETS = (("main20", ROOT / "match_cases.json"),
        ("auxiliary8", ROOT / "match_holdout_cases.json"))


def fixed_batch(case):
    rows = [{"evidence_id": index, "text": body}
            for index, body in enumerate(case["candidates"], 1)]
    ranked = retrieval.rank(case["requirement_quote"], rows, 5, {})
    candidates = []
    for hit in ranked:
        source = hit["row"]
        index = source["evidence_id"]
        candidates.append({"evidence_id": index, "version_id": index,
                           "title": f"가상 경력 {index}", "text": source["text"]})
    return [{"requirement_id": "r1", "kind": "required",
             "requirement_quote": case["requirement_quote"],
             "candidates": candidates}]


def request_for(batch, system_prompt):
    messages = match.messages(batch)
    messages[0]["content"] = system_prompt
    return {"model": MODEL, "messages": messages, "stream": False,
            "think": False, "format": match.SCHEMA, "options": dict(llm.OPTIONS)}


def save(path, report):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(output):
    if output.exists():
        raise FileExistsError(f"기존 평가 결과를 덮어쓰지 않습니다: {output}")
    if match.PROMPT_VERSION != "match-v5":
        raise ValueError("기존 프롬프트 버전이 바뀌어 이 비교를 시작할 수 없습니다")
    candidate_prompt = CANDIDATE.read_text(encoding="utf-8").rstrip("\n")
    prior = json.loads(FACTORIAL.read_text(encoding="utf-8"))
    reused = {entry["case_id"]: entry for entry in prior["calls"]
              if entry["historical_workflow_layout"]}
    if set(reused) != {"source_conflict", "two_sources_support"}:
        raise ValueError("재사용할 두 기존 요청이 없습니다")

    cases = [(set_name, case) for set_name, path in SETS
             for case in json.loads(path.read_text(encoding="utf-8"))["cases"]]
    if len(cases) != 28:
        raise ValueError("고정 평가 사례 28건을 확인할 수 없습니다")
    client = llm.OllamaClient(MODEL, timeout=120)
    model_info = next((item for item in client.local_models() if item.get("name") == MODEL), None)
    if model_info is None or model_info.get("digest") != DIGEST:
        raise ValueError("기존 평가와 동일한 설치 모델 digest가 아닙니다")
    runtime = client._request("/api/version").get("version")
    if runtime != "0.34.4":
        raise ValueError("기존 평가와 동일한 Ollama 런타임이 아닙니다")

    report = {
        "notice": "가상 평가 전용. 실제 출처·제품 프롬프트·기존 결과는 변경하지 않았습니다.",
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL, "model_digest": DIGEST,
        "quantization": model_info.get("details", {}).get("quantization_level"),
        "runtime_version": runtime, "options": dict(llm.OPTIONS),
        "baseline_prompt_version": match.PROMPT_VERSION,
        "baseline_system_prompt": match.SYSTEM_PROMPT,
        "candidate_prompt_version": "match-v8-candidate",
        "candidate_system_prompt": candidate_prompt,
        "top_k": 5, "aliases": [], "timeout_seconds": client.timeout,
        "reused_baseline_file": str(FACTORIAL),
        "cases": [], "new_chat_calls": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    for index, (set_name, case) in enumerate(cases):
        batch = fixed_batch(case)
        entry = {"set": set_name, "id": case["id"],
                 "requirement_quote": case["requirement_quote"],
                 "source_texts": case["candidates"],
                 "expected": case["expected"],
                 "batch": batch, "results": {}}
        report["cases"].append(entry)
        if not batch[0]["candidates"]:
            for variant in ("baseline", "candidate"):
                entry["results"][variant] = {
                    "model_called": False, "assessment": "evidence_not_found",
                    "selected_evidence_ids": [], "matches_expected": True,
                    "reason": "검색 후보가 없어 M1 매칭 모델을 호출하지 않음",
                }
            save(output, report)
            continue

        # Alternate prompt order to avoid putting one variant second in every fresh pair.
        variants = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
        for variant in variants:
            prompt = match.SYSTEM_PROMPT if variant == "baseline" else candidate_prompt
            payload = request_for(batch, prompt)
            request_json = json.dumps(payload, ensure_ascii=False)
            result = {"model_called": True, "attempt": 1,
                      "retry_attempts": 0, "recovery_attempts": 0,
                      "request_json": request_json}
            if variant == "baseline" and case["id"] in reused:
                old = reused[case["id"]]
                if json.loads(old["request_json"]) != payload:
                    raise ValueError(f"기존 요청 전문이 현재 입력과 다릅니다: {case['id']}")
                result.update({
                    "reused": True, "source_file": str(FACTORIAL),
                    "source_call_index": old["call_index"],
                    "raw_response_text": old["raw_response_text"],
                    "server_done": old["server_done"],
                    "server_done_reason": old["server_done_reason"],
                })
            else:
                if report["new_chat_calls"] >= 52:
                    raise RuntimeError("새 매칭 호출 예산 52회를 초과했습니다")
                request = urllib.request.Request(
                    llm.BASE_URL + "/api/chat", data=request_json.encode("utf-8"),
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    method="POST")
                started = time.monotonic()
                result["started_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                report["new_chat_calls"] += 1
                try:
                    with client.opener.open(request, timeout=client.timeout) as response:
                        if response.url != llm.BASE_URL + "/api/chat":
                            raise llm.LocalModelError("로컬 서버의 redirect를 허용하지 않습니다")
                        raw_bytes = response.read(2 * 1024 * 1024 + 1)
                    if len(raw_bytes) > 2 * 1024 * 1024:
                        raise llm.LocalModelError("로컬 모델 응답이 너무 큽니다")
                    result["raw_response_text"] = raw_bytes.decode("utf-8")
                    raw = json.loads(result["raw_response_text"])
                    result["server_done"] = raw.get("done")
                    result["server_done_reason"] = raw.get("done_reason")
                except (OSError, ValueError, llm.LocalModelError) as exc:
                    result["request_error"] = {"type": type(exc).__name__, "message": str(exc)}
                result["elapsed_seconds"] = round(time.monotonic() - started, 3)

            if "raw_response_text" in result:
                raw = json.loads(result["raw_response_text"])
                try:
                    proposal = match.validate(raw.get("message", {}).get("content"), batch)["r1"]
                    result["proposal"] = proposal
                    result["assessment"] = proposal["assessment"]
                    result["selected_evidence_ids"] = proposal["evidence_ids"]
                    result["matches_expected"] = proposal["assessment"] in case["expected"]
                except (match.InvalidMatch, KeyError, TypeError) as exc:
                    result["validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
                    result["matches_expected"] = False
            entry["results"][variant] = result
            save(output, report)
            print(f"{set_name} {case['id']} {variant}: "
                  f"{result.get('assessment', result.get('request_error', result.get('validation_error')))}",
                  flush=True)
            if "request_error" in result:
                report["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                save(output, report)
                return report

    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output)
    print(f"cases: {len(report['cases'])}/28; new match calls: {report['new_chat_calls']}/52")


if __name__ == "__main__":
    main()
