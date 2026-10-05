"""Offline checks for the native Ollama Phase 0.5 evaluator."""

import unittest

from eval import run_agent_phase05_native as native


class NativeEvaluatorTests(unittest.TestCase):
    def test_native_call_parser_requires_one_function_call(self):
        parsed = native.parse_native_tool_call({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "README.md"}}}],
        })
        self.assertTrue(parsed["passed"])
        self.assertEqual(parsed["tool"], "read_file")
        self.assertEqual(parsed["original_args"], {"path": "README.md"})
        self.assertFalse(native.parse_native_tool_call({"role": "assistant", "content": "final"})["passed"])
        self.assertFalse(native.parse_native_tool_call({"role": "assistant", "tool_calls": []})["passed"])

    def test_native_payload_has_tools_and_no_custom_format(self):
        client = native.NativeTraceOllamaClient("synthetic-model")
        client.model_info = {"name": "synthetic-model", "digest": "synthetic", "details": {}}
        client.runtime_version = "synthetic-runtime"
        sent = []

        def fake_request(path, payload=None):
            sent.append(payload)
            return {
                "model": "synthetic-model",
                "message": {"role": "assistant", "content": "", "tool_calls": []},
                "done": True,
                "done_reason": "stop",
            }

        client.request_json = fake_request
        messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "request"}]
        first = client.complete_native(messages)
        messages.extend([
            {"role": "assistant", "content": "", "tool_calls": []},
            {"role": "tool", "tool_name": "list_files", "content": "{}"},
        ])
        second = client.complete_native(messages)

        self.assertEqual(len(sent), 2)
        self.assertIn("tools", sent[0])
        self.assertNotIn("format", sent[0])
        self.assertEqual([m["role"] for m in first["request_payload"]["messages"]], ["system", "user"])
        self.assertEqual([m["role"] for m in second["request_payload"]["messages"]], ["system", "user", "assistant", "tool"])
        self.assertEqual(len(sent[0]["messages"]), 2)

    def test_native_tool_descriptions_include_contract(self):
        by_name = {entry["function"]["name"]: entry for entry in native.NATIVE_TOOLS}
        self.assertEqual(set(by_name), {"list_files", "read_file", "search_text"})
        self.assertNotIn("format", by_name["read_file"])
        self.assertIn("32768", by_name["read_file"]["function"]["description"])
        self.assertIn("workspace-relative", by_name["list_files"]["function"]["description"])

    def test_server_contract_rejects_extra_and_out_of_range_arguments(self):
        extra = native.base.validate_tool_arguments("read_file", {"path": "README.md", "unexpected": 1})
        self.assertFalse(extra["passed"])
        too_long = native.base.validate_tool_arguments("search_text", {"query": "x" * 201})
        self.assertFalse(too_long["passed"])
        too_small = native.base.validate_tool_arguments("read_file", {"path": "README.md", "max_bytes": 0})
        self.assertFalse(too_small["passed"])


if __name__ == "__main__":
    unittest.main()
