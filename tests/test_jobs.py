"""M0 regression cases; every posting and note below is synthetic."""

from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from job_agent import app, storage


SYNTHETIC_JD = "[가상 공고] 예시회사 Python 개발자 모집. 마감: 2026-10-31"


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "jobs.sqlite3"

    def test_relaunch_persists_and_duplicate_preserves_application(self):
        with storage.connect(self.db) as conn:
            first, created = app.register(conn, SYNTHETIC_JD, deadline_date="2026-10-31")
            self.assertTrue(created)
            changed, _ = app.change_application(conn, first["job_id"], 0,
                                                status="submitted", notes="[가상 메모] 지원함")
            self.assertEqual(changed["revision"], 1)
            self.assertIsNone(changed["submitted_at"])

        # A fresh Python process proves persistence beyond a single connection.
        result = subprocess.run(
            [sys.executable, "-m", "job_agent", "--db", str(self.db), "show", "1"],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("[가상 메모] 지원함", result.stdout)
        self.assertIn("상태 submitted", result.stdout)
        event_log = (self.db.parent / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"command": "show"', event_log)
        self.assertNotIn("[가상 메모]", event_log)
        self.assertNotIn(SYNTHETIC_JD, event_log)

        with storage.connect(self.db) as conn:
            again, created = app.register(conn, SYNTHETIC_JD)
            self.assertFalse(created)
            self.assertEqual(again["job_id"], first["job_id"])
            self.assertEqual(again["revision"], 1)
            self.assertEqual(len(storage.list_jobs(conn)), 1)
            separate, created = app.register(conn, SYNTHETIC_JD, new_round=True)
            self.assertTrue(created)
            self.assertNotEqual(separate["job_id"], first["job_id"])

    def test_deadline_validation_and_sorting(self):
        with storage.connect(self.db) as conn:
            original = "  [가상 공고] 날짜 미상\n"
            stored, _ = app.register(conn, original, deadline_raw="10월 중")
            self.assertEqual(stored["raw_text"], original)
            app.register(conn, "[가상 공고] 수시", rolling=True)
            app.register(conn, "[가상 공고] 늦은 날짜", deadline_date="2026-11-02")
            app.register(conn, "[가상 공고] 이른 날짜", deadline_date="2026-10-31")
            rows = storage.list_jobs(conn)
            self.assertEqual([row["job_id"] for row in rows], [4, 3, 1, 2])
            self.assertIsNone(rows[2]["deadline_date"])
            self.assertEqual(rows[2]["deadline_precision"], "unknown")
            self.assertEqual(rows[3]["deadline_precision"], "rolling")
            with self.assertRaises(ValueError):
                app.register(conn, "[가상 공고] 잘못된 날짜", deadline_date="2026-02-30")
            with self.assertRaises(ValueError):
                app.register(conn, "[가상 공고] 잘못된 형식", deadline_date="10/31")
            self.assertEqual(len(storage.list_jobs(conn)), 4)

    def test_revision_conflict_and_noop(self):
        with storage.connect(self.db) as conn:
            row, _ = app.register(conn, SYNTHETIC_JD)
            same, changed = app.change_application(conn, row["job_id"], 0, status="planned")
            self.assertFalse(changed)
            self.assertEqual(same["revision"], 0)
            edited, changed = app.change_application(conn, row["job_id"], 0, notes="[가상 메모]")
            self.assertTrue(changed)
            self.assertEqual(edited["revision"], 1)
            with self.assertRaises(storage.RevisionConflict):
                app.change_application(conn, row["job_id"], 0, status="offer")
            self.assertEqual(storage.get_job(conn, row["job_id"])["status"], "planned")

    def test_failed_insert_rolls_back_job_and_application(self):
        with storage.connect(self.db) as conn:
            # Synthetic database fault after the posting insert, before commit.
            conn.execute("""
                CREATE TRIGGER fail_application BEFORE INSERT ON applications
                BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END;
            """)
            with self.assertRaises(sqlite3.IntegrityError):
                app.register(conn, SYNTHETIC_JD)
            self.assertEqual(conn.execute("SELECT count(*) FROM job_postings").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM applications").fetchone()[0], 0)

    def test_backup_is_readable_snapshot(self):
        destination = Path(self.temp.name) / "backup.sqlite3"
        with storage.connect(self.db) as conn:
            app.register(conn, SYNTHETIC_JD)
            storage.backup(conn, destination)
        with storage.connect(destination) as copied:
            self.assertEqual(len(storage.list_jobs(copied)), 1)


if __name__ == "__main__":
    unittest.main()
