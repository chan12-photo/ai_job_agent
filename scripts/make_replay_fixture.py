"""Build a replay fixture from a recorded agent-read run log.

The fixture keeps, per model turn, the exact request messages and the server
response (or the recorded error), plus the recorded outcome for comparison.
It refuses to write a fixture that contains machine-specific paths.

    python scripts/make_replay_fixture.py --log RUN.json --workspace DIR --out demo/replays/NAME.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_agent import replay  # noqa: E402

spec = importlib.util.spec_from_file_location("check_public_safety", ROOT / "scripts" / "check_public_safety.py")
safety = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safety)

METADATA_KEYS = ("model", "model_digest", "runtime_version", "quantization", "options", "think", "chat_request_flags")


def build_fixture(record: dict, workspace: Path, out: Path, title: str, note: str) -> dict:
    turns = []
    tools_hash = None
    for step in record["steps"]:
        if step.get("kind") != "model":
            continue
        completion = step["completion"]
        payload = completion["request_payload"]
        step_hash = replay.tools_sha256(payload["tools"])
        if tools_hash not in (None, step_hash):
            raise ValueError("tool definitions changed between turns of one run")
        tools_hash = step_hash
        turn = {"expected_messages": payload["messages"]}
        if step.get("error"):
            turn["error"] = {key: step["error"][key] for key in ("type", "message", "n_prompt_tokens", "n_ctx") if key in step["error"]}
        else:
            turn["server_response"] = completion["server_response"]
        turns.append(turn)
    metadata = record.get("model_metadata") or {}
    return {
        "fixture_version": replay.REPLAY_FIXTURE_VERSION,
        "title": title,
        "note": note,
        "question": record["question"],
        "workspace": os.path.relpath(workspace.resolve(), out.parent.resolve()),
        "model_metadata": {key: metadata[key] for key in METADATA_KEYS if key in metadata},
        "tools_sha256": tools_hash,
        "source": {
            "run_id": record["run_id"],
            "log_file": Path(record.get("log_path") or "").name or None,
            "started_at": record.get("started_at"),
            "prompt_version": record.get("prompt_version"),
            "recorded_status": record["status"],
            "recorded_failure_reason": record.get("failure_reason"),
            "recorded_final_answer": record.get("final_answer"),
            "recorded_counts": record.get("counts"),
        },
        "turns": turns,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite existing fixture: {args.out}")
    record = json.loads(args.log.read_text(encoding="utf-8"))
    fixture = build_fixture(record, args.workspace, args.out, args.title, args.note)
    text = json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
    findings = safety.scan_text(str(args.out), text)
    if findings:
        raise SystemExit(f"refusing to write fixture with sensitive content: {findings[:3]}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(json.dumps({"out": str(args.out), "turns": len(fixture["turns"]), "recorded_status": fixture["source"]["recorded_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
