"""Phase 1 demo scorer regression tests."""

from pathlib import Path
import importlib.util
import unittest


RUNNER_PATH = Path(__file__).resolve().parents[1] / "eval" / "run_agent_phase1_cli_demo.py"
spec = importlib.util.spec_from_file_location("phase1_demo_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Phase1DemoScorerTests(unittest.TestCase):
    def test_boolean_answer_contradiction_fails_even_with_correct_evidence(self):
        case = {"id": "demo_02_read_value", "expected_facts": ["enabled", "false"]}
        record = {
            "final_answer": "enabled 값은 true입니다. [E1]",
            "evidence": [{"evidence_id": "E1", "tool": "read_file", "text_preview": '{"enabled": false}'}],
            "steps": [],
        }
        result = runner.facts_ok(case, record)
        self.assertFalse(result["passed"])
        self.assertIn("answer_says_false", result["missing"])

    def test_no_match_answer_contradiction_fails_even_with_empty_search(self):
        case = {"id": "demo_04_search_no_match", "expected_facts": ["MISSING_NEEDLE_42", "no_match"]}
        record = {
            "final_answer": "MISSING_NEEDLE_42를 찾았습니다. [E1]",
            "evidence": [{"evidence_id": "E1", "tool": "search_text", "matches": [], "search_complete": True}],
            "steps": [],
        }
        result = runner.facts_ok(case, record)
        self.assertFalse(result["passed"])
        self.assertIn("answer_reports_no_match", result["missing"])


def search_step(query, path):
    return {"kind": "tool", "executed": True, "tool": "search_text", "original_arguments": {"query": query, "path": path}}


class Phase1DemoScorerV3NegativeTests(unittest.TestCase):
    def test_search_of_wrong_path_fails_even_when_match_is_found(self):
        record = {
            "final_answer": "src/report.py 2행에 CODE_RED가 있습니다 [E1]",
            "evidence": [{"evidence_id": "E1", "tool": "search_text", "search_complete": True,
                          "matches": [{"path": "src/report.py", "line": 2, "text": 'marker = "CODE_RED"'}]}],
            "steps": [search_step("CODE_RED", "src")],
        }
        result = runner.facts_ok({"id": "demo_03_search_file"}, record)
        self.assertFalse(result["passed"])
        self.assertIn("search_args_query_and_file", result["missing"])

    def test_no_match_with_wrong_query_or_path_fails(self):
        record = {
            "final_answer": "MISSING_NEEDLE_42는 없습니다 [E1]",
            "evidence": [{"evidence_id": "E1", "tool": "search_text", "matches": [], "search_complete": True}],
            "steps": [search_step("OTHER_NEEDLE", "src")],
        }
        result = runner.facts_ok({"id": "demo_04_search_no_match"}, record)
        self.assertFalse(result["passed"])
        self.assertIn("search_args_query_and_dir", result["missing"])

    def test_incomplete_empty_search_is_not_a_no_match(self):
        record = {
            "final_answer": "MISSING_NEEDLE_42는 없습니다 [E1]",
            "evidence": [{"evidence_id": "E1", "tool": "search_text", "matches": [], "search_complete": False}],
            "steps": [search_step("MISSING_NEEDLE_42", "docs")],
        }
        result = runner.facts_ok({"id": "demo_04_search_no_match"}, record)
        self.assertFalse(result["passed"])
        self.assertIn("search_completed_with_no_matches", result["missing"])

    def test_negated_boolean_sentences_need_manual_review(self):
        evidence = [{"evidence_id": "E1", "tool": "read_file", "text_preview": '{"enabled": false}'}]
        for answer in ["enabled 값은 true가 아니라 false입니다 [E1]", "enabled는 false가 아니라 true입니다 [E1]"]:
            result = runner.facts_ok({"id": "demo_02_read_value"}, {"final_answer": answer, "evidence": evidence, "steps": []})
            self.assertIsNone(result["passed"], answer)
            self.assertEqual(result["manual_review"], ["answer_says_false"])

    def test_legacy_steps_without_executed_field_keep_their_arguments(self):
        record = {
            "final_answer": "MISSING_NEEDLE_42 검색 결과가 없습니다 [E1]",
            "evidence": [{"evidence_id": "E1", "tool": "search_text", "matches": [], "search_complete": True}],
            "steps": [{"kind": "tool", "tool": "search_text", "original_arguments": {"query": "MISSING_NEEDLE_42", "path": "docs"}}],
        }
        self.assertTrue(runner.facts_ok({"id": "demo_04_search_no_match"}, record)["passed"])
        skipped = dict(record, steps=[dict(record["steps"][0], executed=False)])
        self.assertFalse(runner.facts_ok({"id": "demo_04_search_no_match"}, skipped)["passed"])

    def test_manual_review_is_not_counted_as_case_pass(self):
        rows = [{"passed": False, "facts_check": {"passed": None, "checks": [{"name": "x", "passed": None}]}, "record": {}}]
        summary = runner.summarize(rows)
        self.assertEqual(summary["facts_matched"], 0)
        self.assertEqual(summary["facts_manual_review"], 1)


if __name__ == "__main__":
    unittest.main()
