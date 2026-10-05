"""Replay recorded model responses for the read-only Agent without Ollama.

A replay fixture holds, for each model turn of a real recorded run, the exact
messages that were sent and the server's response.  During replay the runtime
still validates and executes every tool call for real against the workspace;
only the model is replaced.  Before answering each turn the client checks that
the messages the runtime built are identical to the recorded ones, so any
change in code, prompt, tools, or workspace files that alters the conversation
stops the replay instead of silently producing a different run.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import time
from typing import Any

from . import llm, readonly_agent


REPLAY_FIXTURE_VERSION = "readonly-agent-replay-v1"


ReplayMismatch = readonly_agent.ReplayMismatch


def tools_sha256(tools: list[dict[str, Any]]) -> str:
    return readonly_agent.sha256_text(json.dumps(tools, ensure_ascii=False, sort_keys=True))


def load_replay(path: Path) -> dict[str, Any]:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    if fixture.get("fixture_version") != REPLAY_FIXTURE_VERSION:
        raise ValueError(f"unsupported replay fixture version: {fixture.get('fixture_version')}")
    for key in ("question", "workspace", "model_metadata", "tools_sha256", "turns", "source"):
        if key not in fixture:
            raise ValueError(f"replay fixture is missing {key!r}")
    if not fixture["turns"]:
        raise ValueError("replay fixture has no recorded turns")
    fixture["_path"] = str(path)
    return fixture


def replay_workspace(fixture: dict[str, Any]) -> Path:
    """Workspace paths in fixtures are relative to the fixture file."""
    return (Path(fixture["_path"]).parent / fixture["workspace"]).resolve()


def first_difference(expected: list[Any], actual: list[Any]) -> str:
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            return f"message {index} ({left.get('role') if isinstance(left, dict) else '?'}) differs"
    return f"message count differs: recorded {len(expected)}, now {len(actual)}"


class ReplayClient:
    """Drop-in replacement for NativeOllamaClient that serves recorded turns."""

    def __init__(self, fixture: dict[str, Any]):
        self.fixture = fixture
        self.turns = copy.deepcopy(fixture["turns"])
        self.model = fixture["model_metadata"].get("model", readonly_agent.DEFAULT_MODEL)
        self.timeout = 120
        self.chat_attempts = 0
        self.chat_responses = 0
        self.last_failed_completion: dict[str, Any] | None = None

    def prepare_metadata(self) -> dict[str, Any]:
        metadata = copy.deepcopy(self.fixture["model_metadata"])
        metadata["replay"] = {
            "fixture": Path(self.fixture["_path"]).name,
            "fixture_version": REPLAY_FIXTURE_VERSION,
            "recorded_from": copy.deepcopy(self.fixture["source"]),
            "note": "Model responses are replayed from a recorded run; no model was called.",
        }
        return metadata

    def complete_native(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
        self.chat_attempts += 1
        turn_number = self.chat_attempts
        payload = {
            "model": self.model,
            "messages": copy.deepcopy(messages),
            "stream": False,
            "think": False,
            "tools": copy.deepcopy(tools),
            "options": dict(llm.OPTIONS),
            **readonly_agent.CHAT_REQUEST_FLAGS,
        }
        self.last_failed_completion = None
        started = time.monotonic()

        def fail(error: Exception, extra: dict[str, Any] | None = None) -> Exception:
            self.last_failed_completion = {
                "request_payload": copy.deepcopy(payload),
                "server_response": None,
                "message": None,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "done": None,
                "done_reason": None,
                "prompt_tokens": None,
                "output_tokens": None,
                "total_duration_ns": None,
                "load_duration_ns": None,
                "error": {"type": type(error).__name__, "message": str(error), **(extra or {})},
            }
            return error

        if not self.turns:
            raise fail(ReplayMismatch(f"replay diverged: no recorded response for model turn {turn_number}"))
        turn = self.turns.pop(0)
        if tools_sha256(tools) != self.fixture["tools_sha256"]:
            raise fail(ReplayMismatch(f"replay diverged at model turn {turn_number}: tool definitions changed"))
        if messages != turn["expected_messages"]:
            detail = first_difference(turn["expected_messages"], messages)
            raise fail(ReplayMismatch(f"replay diverged at model turn {turn_number}: {detail}"))

        recorded_error = turn.get("error")
        if recorded_error:
            if recorded_error.get("type") == "ContextLimitError":
                error = readonly_agent.ContextLimitError(
                    recorded_error.get("message", "recorded context limit error"),
                    recorded_error.get("n_prompt_tokens"),
                    recorded_error.get("n_ctx"),
                )
                raise fail(error, {"n_prompt_tokens": error.n_prompt_tokens, "n_ctx": error.n_ctx})
            raise fail(llm.LocalModelError(recorded_error.get("message", "recorded model error")))

        response = copy.deepcopy(turn["server_response"])
        self.chat_responses += 1
        return {
            "request_payload": payload,
            "server_response": copy.deepcopy(response),
            "message": copy.deepcopy(response.get("message")),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "done": response.get("done"),
            "done_reason": response.get("done_reason"),
            "prompt_tokens": response.get("prompt_eval_count"),
            "output_tokens": response.get("eval_count"),
            "total_duration_ns": response.get("total_duration"),
            "load_duration_ns": response.get("load_duration"),
        }
