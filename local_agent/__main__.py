"""Command line entry point: python -m local_agent --workspace DIR --question TEXT."""

import argparse
from pathlib import Path
import sys

from . import llm, readonly_agent, replay


def parser():
    cli = argparse.ArgumentParser(
        prog="python -m local_agent",
        description="Answer one question about a local folder with a read-only, policy-checked local model agent.",
    )
    cli.add_argument("--workspace", type=Path, help="folder the agent may read (optional with --replay)")
    cli.add_argument("--question", help="question about the workspace (optional with --replay)")
    cli.add_argument("--replay", type=Path, help="replay recorded model responses from a fixture; tools and policy still run for real")
    cli.add_argument("--prompt-profile", choices=sorted(readonly_agent.PROMPT_PROFILES),
                     help=f"system prompt profile (default {readonly_agent.DEFAULT_PROMPT_PROFILE}; replays use the recorded profile)")
    cli.add_argument("--model", default=readonly_agent.DEFAULT_MODEL, help="installed local Ollama model")
    cli.add_argument("--log-dir", type=Path, default=readonly_agent.DEFAULT_LOG_DIR, help="folder for JSON run logs")
    cli.add_argument("--timeout", type=float, default=readonly_agent.DEFAULT_TOTAL_TIMEOUT_SECONDS, help="overall time limit in seconds")
    cli.add_argument("--max-model-calls", type=int, default=readonly_agent.DEFAULT_MAX_MODEL_CALLS)
    cli.add_argument("--max-tool-calls", type=int, default=readonly_agent.DEFAULT_MAX_TOOL_CALLS)
    cli.add_argument("--json", action="store_true", help="print the full run record as JSON")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        client = None
        workspace, question, model = args.workspace, args.question, args.model
        prompt_profile = args.prompt_profile or readonly_agent.DEFAULT_PROMPT_PROFILE
        if args.replay:
            fixture = replay.load_replay(args.replay)
            if question is not None and question != fixture["question"]:
                raise ValueError("--question differs from the replay fixture question")
            workspace = workspace or replay.replay_workspace(fixture)
            question = fixture["question"]
            client = replay.ReplayClient(fixture)
            model = client.model
            recorded = readonly_agent.PROMPT_PROFILE_BY_VERSION.get(fixture["source"].get("prompt_version"))
            if recorded is None:
                raise ValueError("replay fixture uses an unknown prompt version")
            if args.prompt_profile and args.prompt_profile != recorded:
                raise ValueError("--prompt-profile differs from the profile recorded in the replay fixture")
            prompt_profile = recorded
        elif workspace is None or question is None:
            raise ValueError("--workspace and --question are required unless --replay is given")
        result = readonly_agent.run_question(
            workspace_path=workspace,
            question=question,
            model=model,
            client=client,
            prompt_profile=prompt_profile,
            log_dir=args.log_dir,
            max_model_calls=args.max_model_calls,
            max_tool_calls=args.max_tool_calls,
            total_timeout_seconds=args.timeout,
        )
        readonly_agent.print_result(result, as_json=args.json)
        return readonly_agent.exit_code(result)
    except (ValueError, llm.LocalModelError, OSError, UnicodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("사용자가 실행을 중단했습니다", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
