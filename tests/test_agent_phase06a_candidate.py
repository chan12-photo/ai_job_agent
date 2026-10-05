"""Offline checks for the Phase 0.6-A candidate wrapper."""

import unittest

from eval import run_agent_phase05_native as native
from eval import run_agent_phase06a_candidate as candidate


class Phase06ACandidateWrapperTests(unittest.TestCase):
    def run_with_captured_native_args(self, argv):
        captured = []
        original_main = native.main
        original_prompt = native.SYSTEM_PROMPT
        original_tools = native.NATIVE_TOOLS
        original_versions = (
            native.EVALUATOR_VERSION,
            native.PROMPT_VERSION,
            native.TOOL_CONTRACT_VERSION,
        )

        def fake_main(args):
            captured.extend(args)
            self.assertEqual(native.SYSTEM_PROMPT, candidate.CANDIDATE_SYSTEM_PROMPT)
            self.assertEqual(native.EVALUATOR_VERSION, candidate.CANDIDATE_EVALUATOR_VERSION)
            return 0

        native.main = fake_main
        try:
            exit_code = candidate.main(argv)
        finally:
            native.main = original_main

        self.assertEqual(exit_code, 0)
        self.assertEqual(native.SYSTEM_PROMPT, original_prompt)
        self.assertIs(native.NATIVE_TOOLS, original_tools)
        self.assertEqual(
            (native.EVALUATOR_VERSION, native.PROMPT_VERSION, native.TOOL_CONTRACT_VERSION),
            original_versions,
        )
        return captured

    def test_full_run_does_not_forward_case_id_by_default(self):
        args = self.run_with_captured_native_args([
            "--output", "out.json",
            "--db", "out.sqlite3",
            "--report", "out.md",
        ])
        self.assertNotIn("--case-id", args)

    def test_single_case_run_forwards_explicit_case_id(self):
        args = self.run_with_captured_native_args([
            "--case-id", "basic_06_search_todo_app",
            "--output", "out.json",
            "--db", "out.sqlite3",
            "--report", "out.md",
        ])
        self.assertIn("--case-id", args)
        self.assertEqual(args[args.index("--case-id") + 1], "basic_06_search_todo_app")


if __name__ == "__main__":
    unittest.main()
