"""Run the fixed synthetic matching set against an already installed local model."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from job_agent import llm, match


CASES_PATH = Path(__file__).with_name("match_cases.json")


def evaluate(model_name, cases_path=CASES_PATH):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    client = llm.OllamaClient(model_name)
    results = []
    for case in cases:
        batch = [{"requirement_id": "r1", "kind": "required",
                  "requirement_quote": case["requirement_quote"],
                  "candidates": [{"evidence_id": index, "version_id": 1,
                                  "title": "가상 경력", "text": evidence}
                                 for index, evidence in enumerate(case["candidates"], 1)]}]
        item = {"id": case["id"], "expected": case["expected"],
                "rationale": case["rationale"], "requirement_quote": case["requirement_quote"],
                "candidates": case["candidates"]}
        try:
            response = client.complete(match.messages(batch), match.SCHEMA)
            item["run"] = {key: value for key, value in response.items() if key != "content"}
            item["raw_response"] = response["content"]
            proposal = match.validate(response["content"], batch)["r1"]
            item["proposal"] = proposal
            item["valid"] = True
            item["label_ok"] = proposal["assessment"] in case["expected"]
        except (llm.LocalModelError, match.InvalidMatch) as exc:
            item["valid"] = False
            item["label_ok"] = False
            item["error"] = {"type": type(exc).__name__, "message": str(exc)}
        results.append(item)
        print(f"{case['id']}: {'OK' if item['label_ok'] else 'FAIL'} "
              f"{item.get('proposal', {}).get('assessment', item.get('error', {}).get('type'))}")
    return {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model_name, "prompt_version": match.PROMPT_VERSION,
            "valid": sum(item["valid"] for item in results),
            "label_ok": sum(item["label_ok"] for item in results),
            "total": len(results), "cases": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--trial-suffix-file", type=Path)
    args = parser.parse_args()
    if args.trial_suffix_file:
        match.SYSTEM_PROMPT += "\n" + args.trial_suffix_file.read_text(encoding="utf-8")
        match.PROMPT_VERSION += "+" + args.trial_suffix_file.stem
    result = evaluate(args.model, args.cases)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"valid {result['valid']}/{result['total']}, labels {result['label_ok']}/{result['total']}")


if __name__ == "__main__":
    main()
