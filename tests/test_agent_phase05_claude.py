"""Offline checks for the Phase 0.5 Agent evaluator."""

from pathlib import Path
import tempfile
import unittest

from eval import run_agent_phase05_claude as phase05


class Phase05EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        phase05.create_workspace(self.root)

    def test_read_file_limits_bytes_before_full_success(self):
        result = phase05.policy_and_execute(self.root, "read_file", {"path": "large.txt", "max_bytes": 10})
        self.assertTrue(result["policy_passed"])
        self.assertFalse(result["result"]["ok"])
        self.assertEqual(result["result"]["error"], "file exceeds requested max_bytes")
        self.assertEqual(result["result"]["bytes_read"], 11)

    def test_search_reports_skipped_files_separately_from_no_matches(self):
        result = phase05.policy_and_execute(self.root, "search_text", {"query": "definitely-not-present"})
        self.assertTrue(result["policy_passed"])
        self.assertTrue(result["result"]["ok"])
        self.assertEqual(result["result"]["matches"], [])
        skipped = {row["path"]: row["reason"] for row in result["result"]["skipped"]}
        self.assertIn("large.txt", skipped)
        self.assertIn("links/outside.txt", skipped)
        self.assertIn("src/data.bin", skipped)
        self.assertFalse(result["result"]["search_complete"])

    def test_direct_policy_checks_verify_execution_results(self):
        checks = phase05.direct_policy_checks(self.root)
        self.assertTrue(all(row["passed"] for row in checks))
        binary = next(row for row in checks if row["id"] == "binary_read_is_allowed_but_execution_fails")
        self.assertTrue(binary["actual_policy"])
        self.assertFalse(binary["actual_ok"])
        normal = next(row for row in checks if row["id"] == "normal_file_returns_content")
        self.assertTrue(normal["actual_ok"])
        self.assertIn("Synthetic workspace", normal["result"]["text"])

    def test_non_utf8_and_binary_errors_are_distinct(self):
        non_utf8 = self.root / "notes" / "non_utf8.txt"
        non_utf8.write_bytes(b"\xff\xfe\x00")
        decoded = phase05.policy_and_execute(self.root, "read_file", {"path": "notes/non_utf8.txt"})
        binary = phase05.policy_and_execute(self.root, "read_file", {"path": "src/data.bin"})
        self.assertEqual(decoded["result"]["error"], "binary or non-UTF-8 file")
        self.assertEqual(binary["result"]["error"], "binary file")

    def test_output_paths_are_fresh_and_distinct(self):
        existing = Path(self.temp.name) / "existing.json"
        existing.write_text("{}", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            phase05.validate_output_paths(Path(self.temp.name) / "fresh.sqlite3", existing, None)
        with self.assertRaises(ValueError):
            same = Path(self.temp.name) / "same.out"
            phase05.validate_output_paths(same, same, None)

    def test_trace_client_freezes_each_request_payload(self):
        client = phase05.TraceOllamaClient("synthetic-model")
        client.model_info = {"name": "synthetic-model", "digest": "synthetic", "details": {}}
        client.runtime_version = "synthetic-runtime"
        sent = []

        def fake_request(path, payload=None):
            self.assertEqual(path, "/api/chat")
            sent.append(payload)
            return {
                "model": "synthetic-model",
                "message": {"role": "assistant", "content": "{}"},
                "done": True,
                "done_reason": "stop",
            }

        client.request_json = fake_request
        messages = [{"role": "user", "content": "first"}]
        first = client.complete(messages, {"type": "object"})
        messages.extend([
            {"role": "assistant", "content": "first response"},
            {"role": "tool", "content": "tool result"},
        ])
        second = client.complete(messages, {"type": "object"})

        self.assertEqual(len(sent), 2)
        self.assertEqual([row["role"] for row in first["request_payload"]["messages"]], ["user"])
        self.assertEqual([row["role"] for row in second["request_payload"]["messages"]], ["user", "assistant", "tool"])
        self.assertEqual(len(sent[0]["messages"]), 1)
        self.assertIsNot(first["request_payload"], second["request_payload"])
        self.assertIsNot(first["request_payload"]["messages"], second["request_payload"]["messages"])
        self.assertEqual(first["server_response"]["message"]["role"], "assistant")


if __name__ == "__main__":
    unittest.main()
