"""Evaluate the full M1 path on twenty explicitly synthetic, isolated cases."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from job_agent import app, llm, storage


CASES_PATH = Path(__file__).with_name("match_cases.json")


def evaluate(model_name):
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    client = llm.OllamaClient(model_name)
    results = []
    for case in cases:
        with TemporaryDirectory(prefix="m1-synthetic-") as directory:
            root = Path(directory)
            with storage.connect(root / "jobs.sqlite3") as conn:
                jd_text = ("[가상 공고] 가상회사 분석가 모집. 필수: "
                           + case["requirement_quote"] + ".")
                job, _ = app.register(conn, jd_text)
                source_ids = []
                for index, source_text in enumerate(case["candidates"], 1):
                    path = root / f"source{index}.txt"
                    path.write_text(source_text, encoding="utf-8")
                    _, version_id, _ = app.import_document(
                        conn, path, title=f"가상 경력 {index}", verified=True)
                    source_ids.extend(row["evidence_id"] for row in storage.search_spans(conn, version_id))
                item = {"id": case["id"], "jd_text": jd_text,
                        "expected_assessments": case["expected"],
                        "reference_rationale": case["rationale"],
                        "source_texts": case["candidates"]}
                try:
                    analysis = app.run_workflow(conn, job["job_id"], client)
                    item["analysis"] = analysis
                    extracted = analysis["input_snapshot"].get("extracted")
                    item["extraction_ok"] = bool(extracted and
                         extracted["company"] and extracted["company"]["quote"] == "가상회사" and
                         extracted["position"] and extracted["position"]["quote"] == "분석가" and
                         extracted["deadline_raw"] is None and
                         [(row["kind"], row["quote"]) for row in extracted["requirements"]] ==
                         [("required", case["requirement_quote"])])
                    rows = analysis["result"]["requirements"]
                    outcome = rows[0]["assessment"] if len(rows) == 1 else None
                    item["assessment"] = outcome
                    allowed = [*case["expected"]]
                    if case["id"] == "or_neither":
                        allowed.append("evidence_not_found")
                    item["assessment_ok"] = outcome in allowed
                    retrieved = set(rows[0]["candidate_ids"]) if rows else set()
                    relevant = set() if case["id"] == "or_neither" else set(source_ids)
                    item["relevant_source_count"] = len(relevant)
                    item["relevant_retrieved_count"] = len(relevant & retrieved)
                    selected = [evidence for row in rows for evidence in row["evidence"]]
                    checks = []
                    for evidence in selected:
                        source = app.get_evidence(conn, evidence["evidence_id"])
                        checks.append(
                            evidence["version_id"] == source["version_id"] and
                            evidence["document_id"] == source["document_id"] and
                            evidence["start"] == source["span_start"] and
                            evidence["end"] == source["span_end"] and
                            evidence["text"] == source["text"])
                    item["selected_evidence_count"] = len(selected)
                    item["selected_evidence_valid_count"] = sum(checks)
                    item["source_integrity_ok"] = all(checks)
                    application = storage.get_job(conn, job["job_id"])
                    item["application_unchanged"] = (application["status"] == "planned"
                                                     and application["revision"] == 0)
                except (ValueError, llm.LocalModelError) as exc:
                    item["exception"] = {"type": type(exc).__name__, "message": str(exc)}
                    item["extraction_ok"] = False
                    item["assessment_ok"] = False
                    item["source_integrity_ok"] = False
                    item["selected_evidence_count"] = 0
                    item["selected_evidence_valid_count"] = 0
                    item["application_unchanged"] = False
                    item["relevant_source_count"] = 0
                    item["relevant_retrieved_count"] = 0
                results.append(item)
                print(f"{case['id']}: {item.get('assessment')} "
                      f"extract={item['extraction_ok']} match={item['assessment_ok']}", flush=True)
    relevant = sum(item["relevant_source_count"] for item in results)
    found = sum(item["relevant_retrieved_count"] for item in results)
    return {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model_name, "total": len(results),
            "extraction_ok": sum(item["extraction_ok"] for item in results),
            "retrieval_relevant_found": found, "retrieval_relevant_total": relevant,
            "assessment_ok": sum(item["assessment_ok"] for item in results),
            "source_integrity_ok": sum(item["source_integrity_ok"] for item in results),
            "selected_evidence_count": sum(item["selected_evidence_count"] for item in results),
            "selected_evidence_valid_count": sum(item["selected_evidence_valid_count"] for item in results),
            "application_unchanged": sum(item["application_unchanged"] for item in results),
            "cases": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.model)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({key: report[key] for key in ("total", "extraction_ok", "retrieval_relevant_found",
                                         "retrieval_relevant_total", "assessment_ok",
                                         "source_integrity_ok", "selected_evidence_count",
                                         "selected_evidence_valid_count", "application_unchanged")})


if __name__ == "__main__":
    main()
