# Usage

## Requirements

- Python 3.10 or newer; no third-party packages. Tested on macOS only.
- For live runs: [Ollama](https://ollama.com) with an installed model. The default is `qwen3:4b-instruct-2507-q4_K_M`; for the default model the runtime also checks the installed digest against the one used in the evaluations. Replays need no model.

Start Ollama bound to loopback with cloud models disabled:

```bash
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

## Ask a question

```bash
python3 -m local_agent --workspace path/to/project --question "Which file defines the retry limit?"
```

| Option | Default | Meaning |
|---|---|---|
| `--workspace` | required for live runs | The only folder the agent may read |
| `--question` | required for live runs | One question about that folder |
| `--model` | `qwen3:4b-instruct-2507-q4_K_M` | An installed Ollama model |
| `--prompt-profile` | `v2` | `v3` and `v4` are the experimental injection mitigations from the [injection evaluation](../eval/agent_injection_2026-10-06/REPORT.md) |
| `--max-model-calls` | 4 | Model requests per question (1–8) |
| `--max-tool-calls` | 3 | Tool executions per question (0–8) |
| `--timeout` | 180 | Overall time limit in seconds |
| `--log-dir` | `~/Library/Application Support/LocalAgentLab/runs` | Where the JSON run log is written |
| `--json` | off | Print the full run record instead of the summary |
| `--replay` | — | Serve a recorded run's model responses instead of calling a model (see below) |

## What the agent may read

- Paths must be relative to the workspace. Absolute paths, `..`, and symlinks are rejected, as are `/` and your home folder as a workspace.
- Excluded regardless of letter case: `.env*`, `.git`, SQLite and other database files, key and certificate files (`*.pem`, `*.key`, `*.p12`, `*.pfx`), `.ssh/id_rsa`, `.ssh/id_ed25519`, `.aws/credentials`, `.netrc`, `.ollama/id_ed25519`, logs, model weights, `node_modules`, virtual environments, and the log folder itself.
- Files are read up to 32 KiB (12 KB by default); searches visit at most 1,000 files and skip files over 64 KB. A search that skips anything reports `search_complete=false`.
- If one tool call in a model turn breaks a rule, no call from that turn runs.

## Statuses and exit codes

| Status | Exit | Meaning |
|---|---:|---|
| `completed` | 0 | A final answer with workspace evidence. Not a correctness guarantee. |
| `unverified_final` | 2 | An answer without evidence, or after an incomplete search |
| `policy_or_tool_error` | 1 | A path was rejected or a tool failed |
| `context_budget_exceeded` | 1 | Ollama rejected a prompt longer than `num_ctx` (no silent truncation) |
| `incomplete_model_response` | 1 | The model stopped with `done=false` or `done_reason=length` |
| `repeated_action`, `budget_exhausted`, `protocol_error`, `ollama_error` | 1 | As named |
| `replay_mismatch` | 1 | A replay diverged from its recording |
| `timed_out` / `cancelled` | 124 / 130 | Time limit / Ctrl+C |

If the run log cannot be saved, the command also exits 1 and prints a warning to stderr.

## Run logs

Each run writes one JSON file with the question, every model request and response, every tool call with its policy decision and result, and the evidence used. Logs contain text read from your files and absolute paths, so keep them out of version control (`eval/agent_*_logs_*/` is ignored).

## Replays

```bash
python3 scripts/run_demo.py
python3 -m local_agent --replay demo/replays/03_blocked_env_file.json --log-dir /tmp/agent-demo-logs
```

A replay fixture holds the exact messages and model responses of a recorded run. During replay the policy checks and tools run for real; if the conversation differs from the recording at any turn, the run ends as `replay_mismatch`. New fixtures are built from run logs with `scripts/make_replay_fixture.py`, which refuses output that fails the public-safety scan.

## Reproducing evaluations

Each evaluation has a runner in `eval/` and writes new result files without overwriting old ones. They need a running Ollama with the recorded model. See the [evaluation index](EVALUATION.md) for what each one measures.

```bash
python3 eval/run_agent_phase12_usability.py --output /tmp/usability.json --log-dir /tmp/usability-logs
python3 eval/run_agent_injection_eval.py --set dev --label my-run --agent-arg=--prompt-profile=v4
```

The injection runner refuses to run if any pre-registered file has changed, and the registered test set has already used its two allowed runs.

## Before publishing

```bash
python3 scripts/check_public_safety.py
```

It scans every file git would publish for local paths, email addresses, phone numbers, keys, database or log files, and non-synthetic `.env` files.
