"""Deterministic end-to-end replays of recorded agent runs (no Ollama)."""

import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from local_agent import readonly_agent, replay


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = sorted((ROOT / "demo" / "replays").glob("*.json"))


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log_dir = Path(self.temp.name) / "logs"

    def run_replay(self, fixture, workspace=None):
        return readonly_agent.run_question(
            workspace_path=workspace or replay.replay_workspace(fixture),
            question=fixture["question"],
            log_dir=self.log_dir,
            client=replay.ReplayClient(fixture),
        )

    def test_every_fixture_reproduces_recorded_status_and_answer(self):
        self.assertGreaterEqual(len(FIXTURES), 6)
        for path in FIXTURES:
            with self.subTest(fixture=path.name):
                fixture = replay.load_replay(path)
                record = self.run_replay(fixture)
                self.assertEqual(record["status"], fixture["source"]["recorded_status"])
                self.assertEqual(record["final_answer"], fixture["source"]["recorded_final_answer"])
                self.assertIn("replay", record["model_metadata"])
                self.assertEqual(record["persistence_status"], "saved")

    def test_blocked_fixtures_never_execute_a_tool(self):
        for name in ["03_blocked_env_file.json", "04_blocked_outside_symlink.json"]:
            record = self.run_replay(replay.load_replay(ROOT / "demo" / "replays" / name))
            self.assertEqual(record["counts"]["tool_execution_attempts"], 0, name)
            self.assertEqual(record["evidence"], [], name)

    def test_changed_workspace_file_stops_replay_as_mismatch(self):
        fixture = replay.load_replay(ROOT / "demo" / "replays" / "05_injected_instruction_in_file.json")
        workspace = Path(self.temp.name) / "workspace"
        shutil.copytree(replay.replay_workspace(fixture), workspace, symlinks=True)
        target = workspace / "docs" / "onboarding.md"
        target.write_text(target.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        record = self.run_replay(fixture, workspace=workspace)
        self.assertEqual(record["status"], "replay_mismatch")
        self.assertIn("model turn 2", record["failure_reason"])
        self.assertIsNone(record["final_answer"])

    def test_extra_model_turn_is_a_mismatch_not_a_fabricated_answer(self):
        fixture = copy.deepcopy(replay.load_replay(ROOT / "demo" / "replays" / "01_search_todo_in_file.json"))
        fixture["turns"] = fixture["turns"][:1]
        record = self.run_replay(fixture)
        self.assertEqual(record["status"], "replay_mismatch")
        self.assertIn("no recorded response", record["failure_reason"])


if __name__ == "__main__":
    unittest.main()
