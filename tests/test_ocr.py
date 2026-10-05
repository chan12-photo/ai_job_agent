"""Synthetic macOS Vision OCR and confirmed image registration tests."""

import hashlib
from datetime import datetime, timedelta, timezone
import http.client
from pathlib import Path
import re
import subprocess
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import unittest
import zlib
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

from job_agent import ocr, storage, web


FIXTURES = None
FIXTURE_TEMP = None


def setUpModule():
    global FIXTURES, FIXTURE_TEMP
    if sys.platform != "darwin":
        raise unittest.SkipTest("macOS Vision OCR 전용 시험")
    FIXTURE_TEMP = tempfile.TemporaryDirectory()
    FIXTURES = Path(FIXTURE_TEMP.name)
    script = Path(__file__).with_name("fixture_ocr.swift")
    subprocess.run(["/usr/bin/swift", str(script), str(FIXTURES)],
                   check=True, capture_output=True, text=True, timeout=90)


def tearDownModule():
    if FIXTURE_TEMP:
        FIXTURE_TEMP.cleanup()


class OCRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "synthetic.sqlite3"

    def test_real_vision_mixed_languages_numbers_negation_and_two_columns(self):
        first = ocr.recognize(FIXTURES / "page1.png")
        second = ocr.recognize(FIXTURES / "page2.jpg")
        self.assertIn("데이터 분석가", first)
        self.assertIn("SQL 경험 없음", first)
        self.assertIn("2026-10-31", first)
        self.assertIn("[다른 직무] 디자인", first)
        self.assertIn("English reports required", second)
        self.assertIn("2026-11-15", second)

    def test_rejects_corrupt_oversize_wrong_format_and_excess_pages(self):
        valid = (FIXTURES / "page1.png").read_bytes()
        cases = [
            [("bad.jpg", b"not an image")],
            [("bad.jpg", valid)],
            [("large.png", valid + b"x" * (ocr.MAX_IMAGE_BYTES + 1))],
            [("page.png", valid)] * 6,
        ]
        for uploads in cases:
            with self.subTest(name=uploads[0][0], count=len(uploads)):
                with self.assertRaises(ValueError):
                    ocr.create_draft(self.db, uploads)

    def test_resolution_limit(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        valid = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 9000, 1, 8, 2, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(b'\0' + b'\xff' * 27000)) + chunk(b'IEND', b''))
        with self.assertRaisesRegex(ValueError, "8000픽셀"):
            ocr.create_draft(self.db, [("page.png", valid)])

    def test_registration_failure_rolls_back_job_and_keeps_draft_for_retry(self):
        uploads = [(name, (FIXTURES / name).read_bytes()) for name in ("page1.png", "page2.jpg")]
        draft = ocr.create_draft(self.db, uploads)
        draft["final_text"] = "[가상 공고] 확인한 최종 원문"
        with storage.connect(self.db) as conn:
            conn.execute("CREATE TRIGGER fail_image BEFORE INSERT ON job_images BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                ocr.register_confirmed(conn, self.db, draft)
            self.assertEqual(len(storage.list_jobs(conn)), 0)
            self.assertEqual(len(ocr.load_draft(self.db, draft["id"])["pages"]), 2)
            self.assertFalse(list((ocr.assets_root(self.db) / "images").glob("*/*")))
            conn.execute("DROP TRIGGER fail_image")
            job, created = ocr.register_confirmed(conn, self.db, draft)
            self.assertTrue(created)
        with storage.connect(self.db) as conn:
            self.assertEqual(storage.get_job(conn, job["job_id"])["raw_text"], draft["final_text"])
            self.assertEqual(len(storage.list_job_images(conn, job["job_id"])), 2)
            second = ocr.create_draft(self.db, uploads[:1])
            second["final_text"] = draft["final_text"]
            same, created = ocr.register_confirmed(conn, self.db, second)
            self.assertFalse(created)
            self.assertEqual(same["job_id"], job["job_id"])
            self.assertEqual([r["display_order"] for r in storage.list_job_images(conn, job["job_id"])], [0, 1, 2])

    def test_expired_draft_cleanup_uses_creation_time_even_after_edit(self):
        draft = ocr.create_draft(self.db, [("page.png", (FIXTURES / "page1.png").read_bytes())])
        draft["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        ocr.save_draft(self.db, draft)
        with self.assertRaisesRegex(ValueError, "24시간"):
            ocr.load_draft(self.db, draft["id"])
        ocr.cleanup_drafts(self.db)
        self.assertFalse((ocr.assets_root(self.db) / "drafts" / draft["id"]).exists())


class OCRWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "synthetic-web.sqlite3"
        self.server = web.WebServer(self.db, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def token(self, path="/ocr"):
        status, _, body = self.request("GET", path)
        self.assertEqual(status, 200)
        return re.search(rb'name="_token" value="([^"]+)"', body).group(1).decode()

    def post(self, path, fields):
        draft_page = path.rsplit("/", 1)[0]
        body = urlencode({"_token": self.token(draft_page), **fields}).encode()
        return self.request("POST", path, body, {"Content-Type": "application/x-www-form-urlencoded"})

    def upload(self, files):
        boundary = "synthetic-boundary-ocr"
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="_token"\r\n\r\n{self.token()}\r\n'.encode()]
        for name, content in files:
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="images"; '
                          f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
                         + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.request("POST", "/ocr/upload", b"".join(parts),
                            {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def wait_run(self, run_id):
        for _ in range(200):
            run = self.server.ocr_runs.get(run_id)
            if run and run["state"] in {"finished", "error"}:
                return run
            time.sleep(0.02)
        self.fail("가상 OCR 작업이 끝나지 않았습니다")

    def test_upload_reorder_ocr_correct_register_reopen_and_preserve_images(self):
        files = [(name, (FIXTURES / name).read_bytes()) for name in ("page1.png", "page2.jpg")]
        status, headers, _ = self.upload(files)
        self.assertEqual(status, 303)
        draft_path = headers["Location"]
        draft_id = draft_path.rsplit("/", 1)[1]
        draft = ocr.load_draft(self.db, draft_id)
        png_id = draft["pages"][0]["id"]
        status, _, page = self.request("GET", draft_path)
        self.assertEqual(status, 200)
        self.assertIn("이미지 1 / 2".encode(), page)

        status, _, _ = self.post(draft_path + "/edit", {
            "revision": "0", "action": f"down:{png_id}", "final_text": ""})
        self.assertEqual(status, 303)
        draft = ocr.load_draft(self.db, draft_id)
        self.assertEqual(draft["pages"][0]["mime"], "image/jpeg")

        entered = threading.Event()
        release = threading.Event()
        calls = []

        def fake_ocr(path):
            calls.append(path.suffix)
            entered.set()
            self.assertTrue(release.wait(3))
            return ("English reports required" if path.suffix == ".jpg" else
                    "필수 Python 3년\nSQL 경험 없음\n마감 2026-10-31\n[다른 직무] 디자인")

        with patch("job_agent.web.ocr.recognize", side_effect=fake_ocr):
            status, headers, _ = self.post(draft_path + "/run", {})
            self.assertEqual(status, 303)
            run_path = headers["Location"]
            run_id = urlsplit(run_path).query.split("=", 1)[1]
            self.assertTrue(entered.wait(2))
            status, _, progress = self.request("GET", draft_path)
            self.assertEqual(status, 200)
            self.assertIn("OCR 진행 중".encode(), progress)
            status, second, _ = self.post(draft_path + "/run", {})
            self.assertEqual(status, 303)
            self.assertEqual(second["Location"], run_path)
            release.set()
            self.assertEqual(self.wait_run(run_id)["state"], "finished")
        self.assertEqual(len(calls), 2)
        draft = ocr.load_draft(self.db, draft_id)
        self.assertEqual(draft["revision"], 2)

        corrected = ("[가상 공고] 데이터 분석가\n필수 Python 3년\nSQL 경험 없음\n"
                     "마감 2026-10-31\nEnglish reports required")
        status, headers, _ = self.post(draft_path + "/edit", {
            "revision": "2", "action": "register", "verified": "on",
            "final_text": corrected, "deadline_raw": "2026-10-31",
            "deadline_date": "2026-10-31", "page_" + png_id:
                "필수 Python 3년\nSQL 경험 없음\n마감 2026-10-31"})
        self.assertEqual(status, 303)
        self.assertEqual(urlsplit(headers["Location"]).path, "/jobs/1")
        with storage.connect(self.db) as conn:
            job = storage.get_job(conn, 1)
            self.assertEqual(job["raw_text"], corrected)
            self.assertEqual(job["deadline_date"], "2026-10-31")
            self.assertEqual(job["status"], "planned")
            self.assertEqual(storage.list_analyses(conn, 1), [])
            images = storage.list_job_images(conn, 1)
            self.assertEqual(len(images), 2)
            self.assertEqual(images[0]["mime_type"], "image/jpeg")
            for image in images:
                path = ocr.stored_image_path(self.db, image["file_name"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), image["sha256"])
                status, _, raw = self.request("GET", f"/jobs/1/images/{image['image_id']}")
                self.assertEqual(status, 200)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), image["sha256"])
        self.assertFalse((ocr.assets_root(self.db) / "drafts" / draft_id).exists())
        status, _, detail = self.request("GET", "/jobs/1")
        self.assertEqual(status, 200)
        self.assertIn("등록 당시 확인한 이미지 원본".encode(), detail)

    def test_ocr_failure_keeps_image_and_manual_text_entry(self):
        valid = (FIXTURES / "page1.png").read_bytes()
        status, headers, _ = self.upload([("page1.png", valid)])
        self.assertEqual(status, 303)
        path = headers["Location"]
        with patch("job_agent.web.ocr.recognize", side_effect=ValueError("[가상 실패] 읽기 실패")):
            _, headers, _ = self.post(path + "/run", {})
            run_id = urlsplit(headers["Location"]).query.split("=", 1)[1]
            self.assertEqual(self.wait_run(run_id)["errors"], 1)
        status, _, body = self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertIn("[가상 실패] 읽기 실패".encode(), body)
        self.assertEqual(self.request("GET", "/")[0], 200)
        draft = ocr.load_draft(self.db, path.rsplit("/", 1)[1])
        status, headers, _ = self.post(path + "/edit", {
            "revision": str(draft["revision"]), "action": "register", "verified": "on",
            "final_text": "[가상 공고] 사람이 원본을 보고 직접 입력"})
        self.assertEqual(status, 303)
        with storage.connect(self.db) as conn:
            self.assertEqual(storage.get_job(conn, 1)["raw_text"],
                             "[가상 공고] 사람이 원본을 보고 직접 입력")
            self.assertEqual(len(storage.list_job_images(conn, 1)), 1)

    def test_invalid_upload_shows_error_and_manual_form_remains(self):
        status, _, body = self.upload([("broken.jpg", b"broken")])
        self.assertEqual(status, 400)
        self.assertIn("실제 파일 형식".encode(), body)
        status, _, manual = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("공고 수동 등록".encode(), manual)

    def test_empty_ocr_is_visible_and_does_not_register_automatically(self):
        _, headers, _ = self.upload([("page.png", (FIXTURES / "page1.png").read_bytes())])
        path = headers["Location"]
        with patch("job_agent.web.ocr.recognize", return_value=""):
            _, headers, _ = self.post(path + "/run", {})
            run_id = urlsplit(headers["Location"]).query.split("=", 1)[1]
            self.assertEqual(self.wait_run(run_id)["errors"], 1)
        status, _, body = self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertIn("글자를 찾지 못했습니다".encode(), body)
        with storage.connect(self.db) as conn:
            self.assertEqual(len(storage.list_jobs(conn)), 0)

    def test_confirmation_required_and_registration_never_rewrites_final_text(self):
        _, headers, _ = self.upload([("page.png", (FIXTURES / "page1.png").read_bytes())])
        path = headers["Location"]
        draft_id = path.rsplit("/", 1)[1]
        draft = ocr.load_draft(self.db, draft_id)
        draft["final_text"] = "[가상] 사용자가 확인할 최종 문구"
        ocr.save_draft(self.db, draft)
        fields = {"revision": "1", "action": "register", "final_text": draft["final_text"],
                  "page_" + draft["pages"][0]["id"]: "별도로 고친 이미지 문구"}
        self.assertEqual(self.post(path + "/edit", fields)[0], 400)
        with storage.connect(self.db) as conn:
            self.assertEqual(len(storage.list_jobs(conn)), 0)
        fields.update(revision="2", verified="on")
        self.assertEqual(self.post(path + "/edit", fields)[0], 303)
        with storage.connect(self.db) as conn:
            self.assertEqual(storage.get_job(conn, 1)["raw_text"], draft["final_text"])

    def test_remove_individual_and_last_image(self):
        files = [(name, (FIXTURES / name).read_bytes()) for name in ("page1.png", "page2.jpg")]
        _, headers, _ = self.upload(files)
        path = headers["Location"]
        draft_id = path.rsplit("/", 1)[1]
        for revision in (0, 1):
            draft = ocr.load_draft(self.db, draft_id)
            page = draft["pages"][0]
            status, headers, _ = self.post(path + "/edit", {
                "revision": str(revision), "action": "remove:" + page["id"]})
            self.assertEqual(status, 303)
        self.assertIn("notice=cleared", headers["Location"])
        self.assertEqual(self.request("GET", path)[0], 404)


if __name__ == "__main__":
    unittest.main()
