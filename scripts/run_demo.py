"""Run every replay fixture in demo/replays without Ollama and summarize.

Each replay executes the real policy and tools against the committed synthetic
workspace while serving the model's recorded responses.  The demo passes when
every run reproduces the recorded status and final answer, including the
fixture that documents a known failure.

    python scripts/run_demo.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_agent import readonly_agent, replay  # noqa: E402


def run_fixture(path: Path, log_dir: Path) -> dict:
    fixture = replay.load_replay(path)
    record = readonly_agent.run_question(
        workspace_path=replay.replay_workspace(fixture),
        question=fixture["question"],
        model=fixture["model_metadata"].get("model", readonly_agent.DEFAULT_MODEL),
        log_dir=log_dir,
        client=replay.ReplayClient(fixture),
    )
    source = fixture["source"]
    return {
        "fixture": path.name,
        "title": fixture["title"],
        "question": fixture["question"],
        "status": record["status"],
        "tools": [step["tool"] for step in record["steps"] if step.get("kind") == "tool"],
        "executed": record["counts"]["tool_execution_attempts"],
        "answer": record["final_answer"] or record["failure_reason"] or "",
        "reproduced": record["status"] == source["recorded_status"] and record["final_answer"] == source["recorded_final_answer"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", type=Path, default=ROOT / "demo" / "replays")
    args = parser.parse_args(argv)
    fixtures = sorted(args.replays.glob("*.json"))
    if not fixtures:
        raise SystemExit(f"no replay fixtures in {args.replays}")
    with tempfile.TemporaryDirectory(prefix="agent-demo-logs-") as temp:
        rows = [run_fixture(path, Path(temp)) for path in fixtures]
    for row in rows:
        answer = " ".join(row["answer"].split())
        print(f"\n[{'OK' if row['reproduced'] else 'DIFF'}] {row['title']}")
        print(f"  question : {row['question']}")
        print(f"  tools    : {row['tools'] or '-'} (executed {row['executed']})")
        print(f"  status   : {row['status']}")
        print(f"  answer   : {answer[:160]}{'…' if len(answer) > 160 else ''}")
    reproduced = sum(row["reproduced"] for row in rows)
    print(f"\n{reproduced}/{len(rows)} recorded runs reproduced without calling a model.")
    return 0 if reproduced == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
