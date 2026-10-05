"""Tests for the public-safety scan and path redaction scripts.

Sample sensitive strings are assembled at runtime so this file itself does not
trip the scanner.
"""

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = load("check_public_safety")
redact = load("redact_local_paths")

HOME_PATH = "/" + "Users" + "/alice/project/file.json"
TEMP_PATH = "/private/var/" + "folders" + "/ab/cd123/T/tmpx/ws"
EMAIL = "alice" + "@" + "corp.io"
PHONE = "010" + "-1234-" + "5678"
API_KEY = "sk" + "-" + "A" * 24
KEY_BLOCK = "-----BEGIN " + "RSA PRIVATE KEY-----"


class PublicSafetyScanTests(unittest.TestCase):
    def kinds(self, text):
        return {item["kind"] for item in scan.scan_text("sample.txt", text)}

    def test_detects_paths_contacts_and_secrets(self):
        self.assertIn("absolute_home_path", self.kinds(f"log_path: {HOME_PATH}"))
        self.assertIn("macos_temp_path", self.kinds(TEMP_PATH))
        self.assertIn("email_address", self.kinds(f"contact {EMAIL}"))
        self.assertIn("korean_phone_number", self.kinds(f"tel {PHONE}"))
        self.assertIn("api_key", self.kinds(f"key={API_KEY}"))
        self.assertIn("private_key_block", self.kinds(KEY_BLOCK))

    def test_placeholders_and_allowed_values_are_not_findings(self):
        text = "workspace <repo>/eval/ws, tmp <tmp>/x, home <home>/y, ~/Library/App, /Users/<user>/x, noreply@anthropic.com, a@example.com"
        self.assertEqual(scan.scan_text("sample.txt", text), [])

    def test_forbidden_files_and_non_synthetic_env_are_flagged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "jobs.SQLITE3").write_text("x", encoding="utf-8")
            (root / ".env").write_text("TOKEN=value\n", encoding="utf-8")
            kinds = {item["kind"] for name in ["jobs.SQLITE3", ".env"] for item in scan.scan_file(root, name)}
        self.assertEqual(kinds, {"forbidden_file_type", "env_file"})

    def test_allowlisted_synthetic_env_fixture_passes_only_when_synthetic(self):
        fixture = sorted(scan.SYNTHETIC_ENV_FIXTURES)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / fixture
            path.parent.mkdir(parents=True)
            path.write_text("SYNTHETIC_ONLY_VALUE=marker\n", encoding="utf-8")
            self.assertEqual(scan.scan_file(root, fixture), [])
            path.write_text("TOKEN=real-looking\n", encoding="utf-8")
            self.assertEqual([item["kind"] for item in scan.scan_file(root, fixture)], ["env_file"])


class RedactionTests(unittest.TestCase):
    def test_redaction_replaces_only_path_prefixes(self):
        repo = "/" + "Users" + "/alice/work/repo"
        home = "/" + "Users" + "/alice"
        text = f'{{"workspace": "{repo}/eval/ws", "tmp": "{TEMP_PATH}", "home": "{home}/Library/x", "user": "{home}", "other": "{home}x"}}'
        redacted, counts = redact.redact(text, repo, home)
        self.assertEqual(
            redacted,
            '{"workspace": "<repo>/eval/ws", "tmp": "<tmp>/tmpx/ws", "home": "<home>/Library/x", "user": "<home>", "other": "' + home + 'x"}',
        )
        self.assertEqual(counts, {"<repo>": 1, "<tmp>": 1, "<home>": 2})


if __name__ == "__main__":
    unittest.main()
