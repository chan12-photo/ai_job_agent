"""Measure whether a second local review improves conservative M1 match proposals."""

import argparse
import json
from pathlib import Path

from job_agent import llm, match


REVIEW_PROMPT = """첫 판정이 insufficient_evidence인 항목만 다시 검토한다.
후보의 순서와 개수에 상관없이 모든 원문을 읽는다.
독립된 AND 조건 중 일부가 직접 기록되면 partial이다. 1년 기록과 3년 이상 요구도 partial이다.
두 후보가 같은 가상 활동의 SQL 사용 여부를 서로 반대로 기록하면 conflicting_evidence다.
서로 다른 후보를 합쳐 AND 조건 전부가 직접 확인되면 supported일 수 있다.
팀 성과를 본인 직접 기여로 바꾸거나, 부정문을 긍정 근거로 쓰지 않는다.
첫 판정이 맞으면 그대로 유지한다. JSON Schema로만 답하고 제공된 ID만 사용한다."""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.input.read_text(encoding="utf-8"))
    client = llm.OllamaClient(args.model)
    trials = []
    for case in baseline["cases"]:
        first = case["assessment"]
        if first != "insufficient_evidence":
            continue
        row = case["analysis"]["result"]["requirements"][0]
        candidate_order = row["candidate_ids"]
        sources = {index: text for index, text in enumerate(case["source_texts"], 1)}
        batch = [{"requirement_id": "r1", "kind": "required",
                  "requirement_quote": row["requirement_quote"],
                  "candidates": [{"evidence_id": evidence_id, "version_id": 1,
                                  "title": f"가상 경력 {evidence_id}", "text": sources[evidence_id]}
                                 for evidence_id in candidate_order]}]
        prompt = match.messages(batch)
        prompt[0]["content"] += "\n" + REVIEW_PROMPT
        prompt[1]["content"] += "\n첫 판정: insufficient_evidence"
        trial = {"id": case["id"], "expected": case["expected_assessments"],
                 "first": first, "candidate_order": candidate_order}
        try:
            response = client.complete(prompt, match.SCHEMA)
            trial["raw_response"] = response["content"]
            proposal = match.validate(response["content"], batch)["r1"]
            trial["second"] = proposal["assessment"]
            trial["evidence_ids"] = proposal["evidence_ids"]
            trial["second_ok"] = proposal["assessment"] in case["expected_assessments"]
        except (llm.LocalModelError, match.InvalidMatch) as exc:
            trial["error"] = {"type": type(exc).__name__, "message": str(exc)}
            trial["second_ok"] = False
        trials.append(trial)
        print(trial["id"], trial.get("second", trial.get("error")), trial["second_ok"], flush=True)
    report = {"prompt": REVIEW_PROMPT, "model": args.model,
              "source": str(args.input), "total": len(trials),
              "second_correct": sum(item["second_ok"] for item in trials), "trials": trials}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"second correct {report['second_correct']}/{report['total']}")


if __name__ == "__main__":
    main()
