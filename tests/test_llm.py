"""Synthetic JD extraction tests; no model or network is required."""

import json
from pathlib import Path
import socket
import tempfile
import unittest
import urllib.error

from job_agent import app, jd, llm, storage


RAW_JD = "[가상 공고] 가상회사 개발자 모집. 필수: Python과 SQL 실무 경험. 우대: R 또는 Python. 마감: 10월 중."
VALID = {
    "company": "가상회사",
    "position": "개발자",
    "deadline_raw": "10월 중",
    "requirements": [
        {"kind": "required", "quote": "Python과 SQL 실무 경험"},
        {"kind": "preferred", "quote": "R 또는 Python"},
    ],
}


class FakeLLM:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.calls = 0

    def complete(self, messages, schema):
        self.calls += 1
        assert schema == jd.SCHEMA
        assert messages[0]["role"] == "system"
        return {"content": next(self.contents), "model": "fake", "options": {}}


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "synthetic.sqlite3"

    def test_valid_draft_preserves_quotes_and_application(self):
        with storage.connect(self.db) as conn:
            row, _ = app.register(conn, RAW_JD, deadline_raw="10월 중")
            result = app.analyze_job(conn, row["job_id"], FakeLLM([json.dumps(VALID)]))
            self.assertEqual(result["review_status"], "unreviewed")
            self.assertEqual(result["attempts"], 1)
            self.assertEqual(result["extracted"]["deadline_raw"]["quote"], "10월 중")
            for item in result["extracted"]["requirements"]:
                self.assertEqual(RAW_JD[item["start"]:item["end"]], item["quote"])
            self.assertEqual(storage.get_job(conn, row["job_id"])["revision"], 0)
            self.assertEqual(storage.get_job(conn, row["job_id"])["status"], "planned")

    def test_one_recovery_then_failure_without_db_change(self):
        with storage.connect(self.db) as conn:
            row, _ = app.register(conn, RAW_JD)
            fake = FakeLLM(["not json", json.dumps(VALID)])
            self.assertEqual(app.analyze_job(conn, row["job_id"], fake)["attempts"], 2)
            self.assertEqual(fake.calls, 2)
            fake = FakeLLM(["not json", "still not json"])
            with self.assertRaises(jd.InvalidExtraction):
                app.analyze_job(conn, row["job_id"], fake)
            self.assertEqual(fake.calls, 2)
            self.assertEqual(storage.get_job(conn, row["job_id"])["revision"], 0)

    def test_fabricated_quote_and_missing_fields_rejected(self):
        invented = dict(VALID, deadline_raw="2026-10-31")
        with self.assertRaises(jd.InvalidExtraction):
            jd.validate(RAW_JD, json.dumps(invented))
        missing = {key: value for key, value in VALID.items() if key != "requirements"}
        with self.assertRaises(jd.InvalidExtraction):
            jd.validate(RAW_JD, json.dumps(missing))
        altered = dict(VALID, requirements=[{"kind": "required", "quote": "Kubernetes 경험"}])
        with self.assertRaises(jd.InvalidExtraction):
            jd.validate(RAW_JD, json.dumps(altered))

    def test_document_marker_and_explicit_duty_omission_rejected(self):
        raw = "[가상 공고] 테스트상사 개발자 채용. 주요 업무: API 개발. 필수: Python 경험."
        missing_duty = {"company": "테스트상사", "position": "개발자", "deadline_raw": None,
                        "requirements": [{"kind": "required", "quote": "Python 경험"}]}
        with self.assertRaisesRegex(jd.InvalidExtraction, "업무 항목"):
            jd.validate(raw, json.dumps(missing_duty))
        wrong_company = dict(missing_duty, company="가상 공고", requirements=[
            {"kind": "duty", "quote": "API 개발"}, {"kind": "required", "quote": "Python 경험"}])
        with self.assertRaisesRegex(jd.InvalidExtraction, "자료 표식"):
            jd.validate(raw, json.dumps(wrong_company))
        wrong_company["company"] = "가상"
        with self.assertRaisesRegex(jd.InvalidExtraction, "자료 표식"):
            jd.validate(raw, json.dumps(wrong_company))

    def test_model_error_leaves_manual_and_search_features_available(self):
        class Offline:
            def complete(self, messages, schema):
                raise llm.LocalModelError("offline")

        with storage.connect(self.db) as conn:
            row, _ = app.register(conn, RAW_JD)
            with self.assertRaises(llm.LocalModelError):
                app.analyze_job(conn, row["job_id"], Offline())
            self.assertEqual(storage.get_job(conn, row["job_id"])["status"], "planned")
            self.assertEqual(len(storage.list_jobs(conn)), 1)

    def test_oversize_input_is_rejected_before_model_call(self):
        with storage.connect(self.db) as conn:
            row, _ = app.register(conn, "[가상 공고] " + "A" * jd.MAX_JD_CHARS)
            fake = FakeLLM([])
            with self.assertRaises(ValueError):
                app.analyze_job(conn, row["job_id"], fake)
            self.assertEqual(fake.calls, 0)

    def test_uninstalled_model_is_rejected_before_chat(self):
        client = llm.OllamaClient("missing-model")
        paths = []

        def local_reply(path, payload=None):
            paths.append(path)
            return {"models": [{"name": "qwen3:1.7b"}]}

        client._request = local_reply
        with self.assertRaises(llm.LocalModelError):
            client.complete(jd.messages(RAW_JD), jd.SCHEMA)
        self.assertEqual(paths, ["/api/tags"])

    def test_local_request_timeout_has_distinct_error_type(self):
        class TimeoutOpener:
            def __init__(self, failure):
                self.failure = failure

            def open(self, request, timeout):
                raise self.failure

        client = llm.OllamaClient("synthetic-model")
        for failure in (socket.timeout("synthetic"),
                        urllib.error.URLError(socket.timeout("synthetic"))):
            client.opener = TimeoutOpener(failure)
            with self.assertRaises(llm.ModelTimeout):
                client._request("/api/version")


if __name__ == "__main__":
    unittest.main()
