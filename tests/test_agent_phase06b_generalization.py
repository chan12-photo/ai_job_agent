"""Offline checks for the Phase 0.6-B generalization evaluator."""

import tempfile
import unittest
from pathlib import Path

from eval import run_agent_phase06b_generalization as gen


class Phase06BGeneralizationTests(unittest.TestCase):
    def test_fixture_has_eight_non_basic_cases(self):
        fixture = gen.load_fixture(gen.DEFAULT_FIXTURE)
        case_ids = [case["id"] for case in fixture["cases"]]
        self.assertEqual(len(case_ids), 8)
        self.assertEqual(len(set(case_ids)), 8)
        self.assertFalse(any(case_id.startswith("basic_") for case_id in case_ids))

    def test_workspace_fixture_and_no_match_evidence(self):
        fixture = gen.load_fixture(gen.DEFAULT_FIXTURE)
        case = next(row for row in fixture["cases"] if row["id"] == "gen_08_search_no_match_policy")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            root.mkdir()
            gen.create_workspace(root, fixture)
            outcome = gen.base.policy_and_execute(root, "search_text", case["expected_args"])

        self.assertTrue(outcome["policy_passed"])
        self.assertTrue(outcome["result"]["ok"])
        self.assertEqual(outcome["result"]["matches"], [])
        self.assertTrue(gen.evidence_verified(case, outcome["result"], outcome["normalized_arguments"])["passed"])

    def test_answer_criteria_rejects_unsupported_fact(self):
        fixture = gen.load_fixture(gen.DEFAULT_FIXTURE)
        case = next(row for row in fixture["cases"] if row["id"] == "gen_03_read_brief_summary")
        answer = "Project Orion is an offline production system with customer data."
        result = gen.final_answer_correct(case, answer, evidence_ok=True)
        self.assertFalse(result["passed"])
        self.assertIn("forbidden", result["reason"])

    def test_payload_audit_rejects_mutated_initial_payload(self):
        records = [{
            "case_id": "synthetic",
            "model_generation_attempts": 2,
            "initial": {"request_payload": {"messages": [
                {"role": "system"},
                {"role": "user"},
                {"role": "assistant"},
            ]}},
            "final": {"request_payload": {"messages": [
                {"role": "system"},
                {"role": "user"},
                {"role": "assistant"},
                {"role": "tool"},
            ]}},
        }]
        self.assertFalse(gen.payload_audit(records)["passed"])


if __name__ == "__main__":
    unittest.main()
