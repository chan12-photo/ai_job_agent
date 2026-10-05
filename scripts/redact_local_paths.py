"""Replace machine-specific absolute paths in evaluation evidence with placeholders.

Placeholders:
  <repo>  absolute path of this repository on the machine that produced the file
  <home>  the user's home directory
  <tmp>   a macOS per-user temporary directory (/var/folders/.../T)

The paths are read from the running machine (repository root and Path.home()),
so the script itself contains no user name.  Each run writes a manifest with
the original and redacted SHA-256 of every changed file so the change stays
auditable.  Only literal path prefixes are replaced; no other content changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


TEMP_PATTERN = re.compile(r"(?:/private)?/var/folders/[A-Za-z0-9_+-]+/[A-Za-z0-9_+-]+/T")


def redact(text: str, repo: str, home: str) -> tuple[str, dict[str, int]]:
    counts = {"<repo>": text.count(repo)}
    text = text.replace(repo, "<repo>")
    text, counts["<tmp>"] = TEMP_PATTERN.subn("<tmp>", text)
    counts["<home>"] = text.count(home + "/") + len(re.findall(re.escape(home) + r"(?![A-Za-z0-9._/-])", text))
    text = text.replace(home + "/", "<home>/")
    text = re.sub(re.escape(home) + r"(?![A-Za-z0-9._/-])", "<home>", text)
    return text, {key: value for key, value in counts.items() if value}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args(argv)
    if args.manifest.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {args.manifest}")
    repo = str(Path(__file__).resolve().parents[1])
    home = str(Path.home())
    entries = []
    for path in args.files:
        original = path.read_bytes()
        text, counts = redact(original.decode("utf-8"), repo, home)
        if not counts:
            continue
        redacted = text.encode("utf-8")
        if path.suffix == ".json":
            json.loads(text)  # the redaction must keep JSON valid
        path.write_bytes(redacted)
        entries.append({
            "path": path.as_posix(),
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "redacted_sha256": hashlib.sha256(redacted).hexdigest(),
            "replacements": counts,
        })
    manifest = {
        "purpose": "Machine-specific absolute paths were replaced with placeholders before publishing. Only literal path prefixes changed.",
        "placeholders": {
            "<repo>": "absolute repository root on the author's machine",
            "<home>": "the author's home directory",
            "<tmp>": "macOS per-user temporary directory (/var/folders/.../T)",
        },
        "script": "scripts/redact_local_paths.py",
        "files": entries,
    }
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"changed_files": len(entries), "manifest": str(args.manifest)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
