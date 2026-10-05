"""Synthetic Phase 2 source, version, retrieval, and failure tests."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from job_agent import app, documents, storage


GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "eval" / "search_cases.json").read_text())


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "synthetic.sqlite3"

    def make_file(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_offsets_and_golden_search(self):
        with storage.connect(self.db) as conn:
            for number, sample in enumerate(GOLDEN["documents"]):
                file = self.make_file(f"source{number}.md", sample["text"])
                app.import_document(conn, file, sample["title"], verified=True)
            for case in GOLDEN["cases"]:
                matches = app.search_evidence(conn, case["query"])
                expected = case["expected_excerpt"]
                if expected is None:
                    self.assertEqual(matches, [], case["query"])
                else:
                    self.assertTrue(any(expected in hit["row"]["text"] for hit in matches), case["query"])
                for hit in matches:
                    row = app.get_evidence(conn, hit["row"]["evidence_id"])
                    self.assertEqual(row["raw_text"][row["span_start"]:row["span_end"]], row["text"])
            # A one-letter technology must not match the R in React.
            r_hits = app.search_evidence(conn, "R")
            self.assertEqual(len(r_hits), 1)
            self.assertIn("사용하지", r_hits[0]["row"]["text"])
            alias_hits = app.search_evidence(conn, "파이썬", alias_values=["파이썬=Python"])
            self.assertIn("Python으로", alias_hits[0]["row"]["text"])

    def test_version_replacement_reactivation_and_deduplication(self):
        old_file = self.make_file("old.txt", "[가상 자료] Python 경험\n")
        new_file = self.make_file("new.txt", "[가상 자료] SQL 경험\n")
        with storage.connect(self.db) as conn:
            document_id, old_version, created = app.import_document(conn, old_file,
                                                                      title="가상 문서 이전", verified=True)
            self.assertTrue(created)
            _, same_version, created = app.import_document(conn, old_file,
                                                            replace_document_id=document_id, verified=True)
            self.assertFalse(created)
            self.assertEqual(same_version, old_version)
            _, new_version, created = app.import_document(conn, new_file, title="가상 문서 현재",
                                                           replace_document_id=document_id, verified=True)
            self.assertTrue(created)
            self.assertNotEqual(old_version, new_version)
            self.assertEqual(app.search_evidence(conn, "Python"), [])
            self.assertEqual(len(app.search_evidence(conn, "SQL")), 1)
            self.assertEqual(len(app.search_evidence(conn, "Python", version_id=old_version)), 1)
            self.assertEqual([row["active"] for row in storage.list_versions(conn, document_id)], [0, 1])
            self.assertEqual([row["title"] for row in storage.list_versions(conn, document_id)],
                             ["가상 문서 이전", "가상 문서 현재"])
            old_evidence = app.search_evidence(conn, "Python", version_id=old_version)[0]["row"]
            self.assertEqual(old_evidence["title"], "가상 문서 이전")
            storage.activate_version(conn, old_version)
            self.assertEqual(len(app.search_evidence(conn, "Python")), 1)
            self.assertEqual(app.search_evidence(conn, "SQL"), [])
            self.assertEqual(storage.list_documents(conn)[0]["title"], "가상 문서 이전")

    def test_failed_replacement_preserves_active_version(self):
        old_file = self.make_file("old.md", "# 가상 기록\nPython 사용\n")
        new_file = self.make_file("new.md", "# 가상 기록\nSQL 사용\n")
        with storage.connect(self.db) as conn:
            document_id, old_version, _ = app.import_document(conn, old_file, verified=True)
            conn.execute("""
                CREATE TRIGGER fail_span BEFORE INSERT ON evidence_spans
                BEGIN SELECT RAISE(ABORT, 'synthetic span write failure'); END;
            """)
            with self.assertRaises(sqlite3.IntegrityError):
                app.import_document(conn, new_file, replace_document_id=document_id, verified=True)
            versions = storage.list_versions(conn, document_id)
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["version_id"], old_version)
            self.assertEqual(versions[0]["active"], 1)
            self.assertEqual(len(app.search_evidence(conn, "Python")), 1)

    def test_only_explicit_reviewed_text_or_markdown(self):
        allowed = self.make_file("reviewed.txt", "[가상 자료] 기획 경험")
        blocked = self.make_file("private.pdf", "[가상 자료] 기획 경험")
        symlink = self.root / "shortcut.txt"
        symlink.symlink_to(allowed)
        with storage.connect(self.db) as conn:
            with self.assertRaises(ValueError):
                app.import_document(conn, allowed)
            with self.assertRaises(ValueError):
                app.import_document(conn, blocked, verified=True)
            with self.assertRaises(ValueError):
                app.import_document(conn, symlink, verified=True)
            self.assertEqual(len(storage.list_documents(conn)), 0)

    def test_tampered_span_is_not_presented_as_valid_evidence(self):
        file = self.make_file("source.txt", "[가상 자료] SQL 사용")
        with storage.connect(self.db) as conn:
            app.import_document(conn, file, verified=True)
            conn.execute("UPDATE evidence_spans SET text = '[가상 자료] SQL을 아주 잘함'")
            conn.commit()
            with self.assertRaisesRegex(ValueError, "일치하지 않습니다"):
                app.search_evidence(conn, "SQL")

    def test_conflicting_sources_are_both_returned_without_resolution(self):
        positive = self.make_file("positive.md", "[가상 자료] Python을 사용했습니다.")
        negative = self.make_file("negative.md", "[가상 자료] Python을 사용하지 않았습니다.")
        with storage.connect(self.db) as conn:
            app.import_document(conn, positive, title="가상 자료 A", verified=True)
            app.import_document(conn, negative, title="가상 자료 B", verified=True)
            results = app.search_evidence(conn, "Python")
            self.assertEqual(len(results), 2)
            self.assertEqual({hit["row"]["title"] for hit in results}, {"가상 자료 A", "가상 자료 B"})

    def test_crlf_source_offsets_and_nonexistent_version(self):
        text = "# 가상 제목\r\n첫 문단\r\n\r\n둘째 문단\r\n"
        spans = documents.split_spans(text)
        self.assertEqual(len(spans), 2)
        for _, start, end, excerpt in spans:
            self.assertEqual(text[start:end], excerpt)
        with storage.connect(self.db) as conn:
            with self.assertRaises(ValueError):
                app.search_evidence(conn, "Python", version_id=999)


if __name__ == "__main__":
    unittest.main()
