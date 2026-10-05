"""Local HTTP UI tests using synthetic data and a separate SQLite file."""

import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

from job_agent import app, llm, match, storage, web


SYNTHETIC_JOB = "[가상 공고] 가상회사 분석가 모집. 필수: Python과 SQL 경험."
EXTRACTION = {"company": "가상회사", "position": "분석가", "deadline_raw": None,
              "requirements": [{"kind": "required", "quote": "Python과 SQL 경험"}]}


class FakeModel:
    model = "synthetic-test-model"

    def complete(self, messages, schema):
        if schema == match.SCHEMA:
            item = json.loads(messages[1]["content"].split("\n", 1)[1])["items"][0]
            content = {"matches": [{"requirement_id": item["requirement_id"],
                                    "assessment": "partial",
                                    "evidence_ids": [item["candidates"][0]["evidence_id"]]}]}
        else:
            content = EXTRACTION
        return {"content": json.dumps(content, ensure_ascii=False),
                "model": self.model, "model_digest": "synthetic-digest", "options": {}}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "synthetic-web.sqlite3"
        self.server = None
        self.start_server()

    def start_server(self):
        self.server = web.WebServer(self.db, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        if self.server is not None:
            self.server.shutdown()
            self.thread.join(timeout=3)
            self.server.server_close()
            self.server = None

    def request(self, method, path, fields=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        body = urlencode(fields).encode("utf-8") if fields is not None else None
        request_headers = {"Content-Type": "application/x-www-form-urlencoded"} if fields is not None else {}
        request_headers.update(headers or {})
        try:
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode("utf-8")
        finally:
            conn.close()

    def token(self):
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        return re.search(r'name="_token" value="([^"]+)"', body).group(1)

    def post(self, path, fields):
        return self.request("POST", path, {"_token": self.token(), **fields})

    def test_register_edit_reopen_and_keep_unknown_deadline(self):
        status, headers, _ = self.post("/jobs", {"raw_text": SYNTHETIC_JOB,
                                                  "deadline_raw": "10월 중"})
        self.assertEqual(status, 303)
        self.assertIn("notice=created", headers["Location"])
        job_path = urlsplit(headers["Location"]).path
        status, _, detail = self.request("GET", job_path)
        self.assertEqual(status, 200)
        self.assertIn("10월 중 · 날짜 미확인", detail)

        status, headers, _ = self.post("/jobs", {"raw_text": SYNTHETIC_JOB})
        self.assertEqual(status, 303)
        self.assertIn("notice=existing", headers["Location"])
        self.assertEqual(urlsplit(headers["Location"]).path, job_path)

        status, _, _ = self.post(job_path + "/application", {
            "revision": "0", "status": "preparing", "notes": "[가상 메모] 포트폴리오 검토"})
        self.assertEqual(status, 303)
        with storage.connect(self.db) as conn:
            row = storage.get_job(conn, 1)
            self.assertEqual(row["status"], "preparing")
            self.assertEqual(row["deadline_precision"], "unknown")
            self.assertIsNone(row["deadline_date"])
            self.assertEqual(row["notes"], "[가상 메모] 포트폴리오 검토")
            self.assertEqual(len(storage.list_jobs(conn)), 1)

        self.stop_server()
        self.start_server()
        status, _, detail = self.request("GET", job_path)
        self.assertEqual(status, 200)
        self.assertIn("[가상 메모] 포트폴리오 검토", detail)
        self.assertIn("준비 중", detail)
        self.assertIn("10월 중 · 날짜 미확인", detail)

    def test_saved_analysis_shows_source_unselected_candidate_and_human_review(self):
        with storage.connect(self.db) as conn:
            job, _ = app.register(conn, SYNTHETIC_JOB)
            for name, content in (
                ("[가상 자료] 수행 기록", "# 가상 기록\nPython을 사용했습니다.\n"),
                ("[가상 자료] 다른 기록", "# 가상 기록\nSQL을 사용하지 않았습니다.\n"),
            ):
                path = self.root / f"doc-{len(storage.list_documents(conn))}.md"
                path.write_text(content, encoding="utf-8")
                app.import_document(conn, path, name, verified=True)
            analysis = app.run_workflow(conn, job["job_id"], FakeModel())
            self.assertEqual(analysis["status"], "review_ready")
            self.assertEqual(len(analysis["result"]["requirements"][0]["candidates"]), 2)
            analysis_id = analysis["analysis_id"]

        status, _, body = self.request("GET", f"/analyses/{analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("AI 판정은 검토 전 초안", body)
        self.assertIn("partial은 전체 요건 충족을 뜻하지 않습니다", body)
        self.assertIn("모델이 선택한 근거", body)
        self.assertIn("모델이 선택하지 않은 검색 후보", body)
        self.assertIn("[가상 자료] 수행 기록", body)
        self.assertIn("[가상 자료] 다른 기록", body)
        self.assertIn("Python을 사용했습니다", body)
        self.assertIn("SQL을 사용하지 않았습니다", body)
        self.assertIn("match-v5", body)
        # Extracted fields are stored as verified source spans, not plain strings.
        company_start = SYNTHETIC_JOB.index("가상회사")
        self.assertIn(f"회사: 가상회사 [{company_start}:{company_start + 4}]", body)
        self.assertNotIn("&#x27;quote&#x27;", body)
        self.assertNotIn("'quote'", body)

        status, _, _ = self.post(f"/analyses/{analysis_id}/review", {
            "revision": "0", "review_status": "needs_changes"})
        self.assertEqual(status, 303)
        with storage.connect(self.db) as conn:
            updated = app.get_analysis(conn, analysis_id)
            self.assertEqual(updated["review_status"], "needs_changes")
            self.assertEqual(storage.get_job(conn, job["job_id"])["status"], "planned")

    def test_offline_analysis_dedupes_and_preserves_management(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        class OfflineModel:
            def __init__(self, model):
                self.model = model

            def complete(self, messages, schema):
                calls.append(1)
                entered.set()
                if not release.wait(3):
                    raise AssertionError("가상 Ollama 대기 제한")
                raise llm.LocalModelError("[가상 시험] Ollama 연결 불가")

        with storage.connect(self.db) as conn:
            job, _ = app.register(conn, SYNTHETIC_JOB)
        with patch("job_agent.web.llm.OllamaClient", OfflineModel):
            status, headers, _ = self.post("/jobs/1/analysis", {"model": "synthetic-offline"})
            self.assertEqual(status, 303)
            run_path = headers["Location"]
            self.assertTrue(entered.wait(2))
            status, _, progress = self.request("GET", run_path)
            self.assertEqual(status, 200)
            self.assertIn("진행 중", progress)
            self.assertIn("http-equiv=\"refresh\"", progress)
            status, second_headers, _ = self.post("/jobs/1/analysis", {"model": "synthetic-offline"})
            self.assertEqual(status, 303)
            self.assertEqual(second_headers["Location"], run_path)
            self.assertEqual(len(calls), 1)
            release.set()
            for _ in range(100):
                run = self.server.runs.get(urlsplit(run_path).query.split("=", 1)[1])
                if run["state"] == "finished":
                    break
                time.sleep(0.02)
            else:
                self.fail("가상 오프라인 분석이 끝나지 않았습니다")

        self.assertEqual(run["result_status"], "failed")
        status, _, body = self.request("GET", run_path)
        self.assertEqual(status, 200)
        self.assertIn("분석 기록이 저장됐습니다", body)
        self.assertIn("분석 실패 · 단계 오류 확인 필요", body)
        with storage.connect(self.db) as conn:
            self.assertEqual(len(storage.list_analyses(conn, job["job_id"])), 1)
            self.assertEqual(storage.get_job(conn, job["job_id"])["status"], "planned")
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/analyses/1")[0], 200)

    def test_rejects_foreign_host_and_missing_csrf(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/jobs", {"raw_text": SYNTHETIC_JOB})[0], 403)
        self.assertEqual(self.request("POST", "/jobs", {"_token": self.token(),
                         "raw_text": SYNTHETIC_JOB}, headers={"Origin": "https://evil.example"})[0], 403)
        with storage.connect(self.db) as conn:
            self.assertEqual(len(storage.list_jobs(conn)), 0)

        # The in-app browser uses a null Origin for local form submissions.
        self.assertEqual(self.request("POST", "/jobs", {"_token": self.token(),
                         "raw_text": SYNTHETIC_JOB}, headers={"Origin": "null"})[0], 303)


if __name__ == "__main__":
    unittest.main()
