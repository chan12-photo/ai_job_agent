"""Run a small, synthetic JD extraction comparison against installed local models."""

import argparse
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from job_agent import app, jd, llm, storage


def extract_quote(value):
    return value["quote"] if value else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True, help="이미 설치된 로컬 모델명")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("jd_cases.json"),
                        help="가상 JD와 사람이 적은 정답 JSON")
    parser.add_argument("--output", type=Path, help="가상 평가 결과 JSON 저장 경로")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    report = {"prompt_version": jd.PROMPT_VERSION, "case_count": len(cases),
              "request_options": dict(llm.OPTIONS), "think": False, "models": []}
    with TemporaryDirectory() as directory:
        with storage.connect(Path(directory) / "synthetic.sqlite3") as conn:
            job_ids = [app.register(conn, case["text"])[0]["job_id"] for case in cases]
            for model in args.model:
                client = llm.OllamaClient(model)
                results = []
                for case, job_id in zip(cases, job_ids):
                    started = perf_counter()
                    try:
                        result = app.analyze_job(conn, job_id, client)
                        extracted = result["extracted"]
                        expected = case["expected"]
                        correct = {field: extract_quote(extracted[field]) == expected[field]
                                   for field in ("company", "position", "deadline_raw")}
                        got_requirements = {(item["kind"], item["quote"])
                                            for item in extracted["requirements"]}
                        correct["requirements"] = got_requirements == {
                            tuple(item) for item in expected["requirements"]}
                        results.append({"id": case["id"], "status": "validated",
                                        "seconds": round(perf_counter() - started, 3),
                                        "attempts": result["attempts"], "correct": correct,
                                        "actual": {field: extract_quote(extracted[field])
                                                   for field in ("company", "position", "deadline_raw")},
                                        "actual_requirements": sorted(got_requirements),
                                        "model_digest": result["run"].get("model_digest"),
                                        "quantization": result["run"].get("quantization")})
                    except (ValueError, llm.LocalModelError) as exc:
                        results.append({"id": case["id"], "status": "failed",
                                        "seconds": round(perf_counter() - started, 3),
                                        "error_type": type(exc).__name__,
                                        "correct": {field: False for field in
                                                    ("company", "position", "deadline_raw", "requirements")}})
                summary = {field: sum(item["correct"][field] for item in results)
                           for field in ("company", "position", "deadline_raw", "requirements")}
                report["models"].append({"model": model, "summary_correct": summary,
                                         "first_attempt_valid": sum(item.get("attempts") == 1 for item in results),
                                         "validated": sum(item["status"] == "validated" for item in results),
                                         "median_seconds": round(median(item["seconds"] for item in results), 3),
                                         "cases": results})
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
