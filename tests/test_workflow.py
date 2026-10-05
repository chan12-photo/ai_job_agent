"""Synthetic M1 persistence, source validation, and failure isolation tests."""

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_agent import app, jd, llm, match, storage
from job_agent.__main__ import main, print_analysis


JD_TEXT = "[가상 공고] 가상회사 분석가 모집. 필수: Python과 SQL 경험."
EXTRACTION = {"company": "가상회사", "position": "분석가", "deadline_raw": None,
              "requirements": [{"kind": "required", "quote": "Python과 SQL 경험"}]}


class FakeModel:
    model = "synthetic-model"

    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = 0

    def complete(self, messages, schema):
        self.calls += 1
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            answer = answer(messages, schema)
        return {"content": json.dumps(answer, ensure_ascii=False) if isinstance(answer, dict) else answer,
                "model": self.model, "model_digest": "synthetic-digest", "options": {}}


def proposal(messages, schema):
    assert schema == match.SCHEMA
    batch = json.loads(messages[1]["content"].split("\n", 1)[1])["items"]
    return {"matches": [{"requirement_id": item["requirement_id"], "assessment": "partial",
                         "evidence_ids": [item["candidates"][0]["evidence_id"]]}
                        for item in batch]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "synthetic.sqlite3"

    def prepare(self, conn, with_doc=True):
        job, _ = app.register(conn, JD_TEXT)
        if with_doc:
            path = self.root / "synthetic.md"
            path.write_text("# 가상 경력\nPython을 사용했습니다.\n", encoding="utf-8")
            app.import_document(conn, path, "가상 경력", verified=True)
        return job["job_id"]

    def test_persisted_reviewable_evidence_and_application_unchanged(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            model = FakeModel([EXTRACTION, proposal])
            result = app.run_workflow(conn, job_id, model)
            self.assertEqual(result["status"], "review_ready")
            self.assertEqual(result["review_status"], "pending")
            self.assertEqual(model.calls, 2)
            item = result["result"]["requirements"][0]
            self.assertEqual(item["assessment"], "partial")
            self.assertEqual(item["missing_conditions"], "Python과 SQL 경험")
            self.assertIn("모델 제안", item["reason"])
            evidence = item["evidence"][0]
            self.assertEqual(evidence["text"], app.get_evidence(conn, evidence["evidence_id"])["text"])
            self.assertEqual(evidence["version_id"], result["source_version_ids"][0])
            self.assertEqual(evidence["document_id"], 1)
            self.assertIn("start", evidence)
            self.assertEqual(storage.get_job(conn, job_id)["status"], "planned")
            self.assertEqual(storage.get_job(conn, job_id)["revision"], 0)
            analysis_id = result["analysis_id"]
        with storage.connect(self.db) as conn:
            self.assertEqual(app.get_analysis(conn, analysis_id)["result"], result["result"])
            self.assertEqual(len(storage.list_analyses(conn, job_id)), 1)

    def test_no_candidate_is_explicit_and_does_not_call_match_model(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn, with_doc=False)
            model = FakeModel([EXTRACTION])
            result = app.run_workflow(conn, job_id, model)
            self.assertEqual(result["status"], "no_evidence")
            self.assertEqual(result["result"]["requirements"][0]["assessment"], "evidence_not_found")
            self.assertEqual(model.calls, 1)

    def test_invalid_evidence_id_retried_then_isolated(self):
        bad = {"matches": [{"requirement_id": "r1", "assessment": "supported",
                            "evidence_ids": [999999]}]}
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            model = FakeModel([EXTRACTION, bad, bad])
            result = app.run_workflow(conn, job_id, model)
            self.assertEqual(model.calls, 3)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["result"]["requirements"][0]["evidence"], [])
            self.assertEqual(result["result"]["requirements"][0]["error"], "InvalidMatch")
            self.assertEqual(storage.get_job(conn, job_id)["revision"], 0)

    def test_extract_failure_is_saved_without_application_change(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            result = app.run_workflow(conn, job_id, FakeModel(["invalid", "invalid"]))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["result"]["errors"][0]["stage"], "extract")
            self.assertEqual(storage.get_job(conn, job_id)["status"], "planned")

    def test_version_warning_and_review_revision(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            result = app.run_workflow(conn, job_id, FakeModel([EXTRACTION, proposal]))
            analysis_id = result["analysis_id"]
            doc_id = storage.list_documents(conn)[0]["document_id"]
            path = self.root / "new.md"
            path.write_text("# 가상 경력\nSQL을 사용했습니다.\n", encoding="utf-8")
            app.import_document(conn, path, "가상 경력 수정", replace_document_id=doc_id, verified=True)
            self.assertEqual(app.get_analysis(conn, analysis_id)["previous_version_ids"], [1])
            reviewed = app.review_analysis(conn, analysis_id, 0, "reviewed")
            self.assertEqual((reviewed["review_status"], reviewed["revision"]), ("reviewed", 1))
            with self.assertRaises(storage.RevisionConflict):
                app.review_analysis(conn, analysis_id, 0, "needs_changes")

    def test_analysis_write_failure_keeps_existing_records_intact(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            conn.execute("""CREATE TRIGGER fail_analysis BEFORE INSERT ON analysis_results
                            BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
            with self.assertRaises(sqlite3.IntegrityError):
                app.run_workflow(conn, job_id, FakeModel([EXTRACTION, proposal]))
            self.assertEqual(len(storage.list_analyses(conn)), 0)
            self.assertEqual(storage.get_job(conn, job_id)["status"], "planned")
            self.assertEqual(len(storage.list_documents(conn)), 1)

    def test_validator_rejects_unsupported_claim_without_evidence(self):
        batch = [{"requirement_id": "r1", "requirement_quote": "Python 경험",
                  "candidates": [{"evidence_id": 1}]}]
        output = {"matches": [{"requirement_id": "r1", "assessment": "supported",
                               "evidence_ids": []}]}
        with self.assertRaises(match.InvalidMatch):
            match.validate(json.dumps(output), batch)

    def test_validator_rejects_extra_free_text(self):
        batch = [{"requirement_id": "r1", "requirement_quote": "Python과 SQL 경험",
                  "candidates": [{"evidence_id": 1}]}]
        invented = {"matches": [{"requirement_id": "r1", "assessment": "partial",
                                 "evidence_ids": [1]}]}
        invented["matches"][0]["reason"] = "기록 없음 → 경험 부재"
        with self.assertRaises(match.InvalidMatch):
            match.validate(json.dumps(invented), batch)

    def test_empty_extraction_is_not_marked_review_ready(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            empty = dict(EXTRACTION, requirements=[])
            result = app.run_workflow(conn, job_id, FakeModel([empty]))
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["result"]["errors"][0]["type"], "no_requirements_extracted")

    def test_expired_total_budget_skips_model_call(self):
        model = FakeModel([])
        with self.assertRaises(llm.WorkflowTimeout):
            app._complete(model, [], jd.SCHEMA, deadline=0)
        self.assertEqual(model.calls, 0)

    def test_timeout_and_user_cancel_are_saved_at_both_model_stages(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            cases = [
                ([llm.ModelTimeout("가상 요청 시간 초과")], "timed_out", "extract"),
                ([KeyboardInterrupt()], "cancelled", "extract"),
                ([EXTRACTION, llm.ModelTimeout("가상 요청 시간 초과")], "timed_out", "match"),
                ([EXTRACTION, KeyboardInterrupt()], "cancelled", "match"),
            ]
            for answers, status, stage in cases:
                result = app.run_workflow(conn, job_id, FakeModel(answers))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["result"]["errors"][0]["stage"], stage)
                self.assertEqual(storage.get_job(conn, job_id)["status"], "planned")
                self.assertEqual(storage.get_job(conn, job_id)["revision"], 0)
        with storage.connect(self.db) as conn:
            self.assertEqual([row["status"] for row in storage.list_analyses(conn)],
                             ["cancelled", "timed_out", "cancelled", "timed_out"])

    def test_retrieval_cancel_is_saved_without_changing_application(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            with patch("job_agent.app.retrieval.rank", side_effect=KeyboardInterrupt()):
                result = app.run_workflow(conn, job_id, FakeModel([EXTRACTION]))
            self.assertEqual(result["status"], "cancelled")
            self.assertEqual(result["result"]["errors"][-1]["stage"], "retrieve")
            self.assertEqual(storage.get_job(conn, job_id)["status"], "planned")
            self.assertEqual(storage.get_job(conn, job_id)["revision"], 0)
        with storage.connect(self.db) as conn:
            self.assertEqual(app.get_analysis(conn, result["analysis_id"])["status"], "cancelled")

    def test_retrieval_elapsed_budget_is_saved_as_timeout(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            with patch("job_agent.app.monotonic", side_effect=[0, 1, 1, 1, 301]):
                result = app.run_workflow(conn, job_id, FakeModel([EXTRACTION]))
            self.assertEqual(result["status"], "timed_out")
            self.assertEqual(result["result"]["errors"][-1]["stage"], "retrieve")
            self.assertEqual(storage.get_job(conn, job_id)["status"], "planned")

    def test_cli_exit_code_matches_saved_run_status(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
        bad = {"matches": [{"requirement_id": "r1", "assessment": "supported",
                            "evidence_ids": [999999]}]}
        cases = [
            (FakeModel([EXTRACTION, proposal]), 0, "review_ready"),
            (FakeModel([EXTRACTION, bad, bad]), 2, "partial"),
            (FakeModel(["invalid", "invalid"]), 1, "failed"),
            (FakeModel([llm.ModelTimeout("가상 시간 초과")]), 1, "timed_out"),
            (FakeModel([KeyboardInterrupt()]), 130, "cancelled"),
        ]
        for fake, expected_code, expected_status in cases:
            with patch("job_agent.__main__.llm.OllamaClient", return_value=fake):
                with redirect_stdout(StringIO()):
                    code = main(["--db", str(self.db), "run", str(job_id), "--model", "synthetic-model"])
            self.assertEqual(code, expected_code)
            with storage.connect(self.db) as conn:
                self.assertEqual(storage.list_analyses(conn)[0]["status"], expected_status)

    def test_cli_interrupt_outside_model_stage_exits_without_traceback(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
        with patch("job_agent.__main__.app.run_workflow", side_effect=KeyboardInterrupt()):
            with patch("job_agent.__main__.llm.OllamaClient", return_value=FakeModel([])):
                with patch("sys.stderr", new_callable=StringIO) as stderr:
                    code = main(["--db", str(self.db), "run", str(job_id),
                                 "--model", "synthetic-model"])
        self.assertEqual(code, 130)
        self.assertIn("사용자가 실행을 중단했습니다", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        with storage.connect(self.db) as conn:
            self.assertEqual(storage.list_analyses(conn), [])

    def test_existing_analysis_schema_migrates_without_losing_review(self):
        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn)
            analysis = app.run_workflow(conn, job_id, FakeModel([EXTRACTION, proposal]))
            app.review_analysis(conn, analysis["analysis_id"], 0, "needs_changes")
        raw = sqlite3.connect(self.db)
        try:
            with raw:
                raw.execute("""
                    CREATE TABLE analysis_results_old (
                        analysis_id INTEGER PRIMARY KEY,
                        run_id TEXT NOT NULL UNIQUE,
                        job_id INTEGER NOT NULL REFERENCES job_postings(job_id),
                        status TEXT NOT NULL CHECK(status IN
                            ('review_ready','partial','no_evidence','failed')),
                        input_snapshot TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        source_version_ids TEXT NOT NULL,
                        run_manifest TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        review_status TEXT NOT NULL DEFAULT 'pending'
                            CHECK(review_status IN ('pending','reviewed','needs_changes')),
                        revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
                    )
                """)
                raw.execute("INSERT INTO analysis_results_old SELECT * FROM analysis_results")
                raw.execute("DROP TABLE analysis_results")
                raw.execute("ALTER TABLE analysis_results_old RENAME TO analysis_results")
        finally:
            raw.close()
        with storage.connect(self.db) as conn:
            restored = app.get_analysis(conn, analysis["analysis_id"])
            self.assertEqual(restored["review_status"], "needs_changes")
            self.assertEqual(restored["revision"], 1)
            self.assertEqual(restored["run_id"], analysis["run_id"])
            job = storage.get_job(conn, job_id)
            self.assertEqual(job["status"], "planned")
            self.assertEqual(job["revision"], 0)
            timeout = app.run_workflow(conn, job_id, FakeModel([llm.ModelTimeout("가상 시간 초과")]))
            self.assertEqual(timeout["status"], "timed_out")

    def test_unselected_candidate_is_visible_for_manual_review(self):
        def only_first(messages, schema):
            batch = json.loads(messages[1]["content"].split("\n", 1)[1])["items"]
            return {"matches": [{"requirement_id": "r1", "assessment": "insufficient_evidence",
                                 "evidence_ids": [batch[0]["candidates"][0]["evidence_id"]]}]}

        with storage.connect(self.db) as conn:
            job_id = self.prepare(conn, with_doc=False)
            for index, text in enumerate(("Python을 사용했습니다.", "SQL을 사용하지 않았습니다."), 1):
                path = self.root / f"source{index}.txt"
                path.write_text(text, encoding="utf-8")
                app.import_document(conn, path, f"가상 문서 {index}", verified=True)
            result = app.run_workflow(conn, job_id, FakeModel([EXTRACTION, only_first]))
            row = result["result"]["requirements"][0]
            self.assertEqual(len(row["candidates"]), 2)
            output = StringIO()
            with redirect_stdout(output):
                print_analysis(result, conn)
            self.assertIn("모델이 선택하지 않은 검색 후보", output.getvalue())
            self.assertIn("SQL을 사용하지 않았습니다", output.getvalue())
            del row["candidates"]  # Results saved before this change still resolve candidate IDs.
            output = StringIO()
            with redirect_stdout(output):
                print_analysis(result, conn)
            self.assertIn("SQL을 사용하지 않았습니다", output.getvalue())
            result["run_manifest"]["match_prompt_version"] = "match-v2"
            output = StringIO()
            with redirect_stdout(output):
                print_analysis(result, conn)
            self.assertIn("모델이 자유롭게 쓴 해석 문장", output.getvalue())


if __name__ == "__main__":
    unittest.main()
