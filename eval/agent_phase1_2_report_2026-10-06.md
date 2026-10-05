# Phase 1.2 read-only Agent stabilization report

## Scope

This work stabilizes the existing Phase 1.1 read-only CLI Agent. It does not add write, delete, shell, Git, UI, web scraping, PDF, new model, cloud fallback, or autonomous multi-tool frameworks. The exposed Agent tools remain `list_files`, `read_file`, and `search_text`.

The job-posting analysis code, `match-v5`, OCR flow, product DB schema, and existing raw evaluation outputs were not changed.

## Confirmed issues fixed

| Area | Confirmed behavior before | Fix |
|---|---|---|
| Exclusion case variants | Names such as `.ENV`, `.GIT`, `*.SQLITE3`, `*.ASSETS` could bypass lowercase-only exclusions | Exclusion names and patterns are compared case-insensitively for policy checks while preserving the original requested path in logs |
| Representative secrets | `.ssh/id_rsa`, `.aws/credentials`, `.netrc`, `.ollama/id_ed25519` were not explicitly blocked | Added minimal sensitive path exclusions and tests using only synthetic files |
| Excluded roots | Log directory exclusion did not account for case variants and needed clear boundary checks | Added component-wise boundary comparison, including case-insensitive checks for policy exclusion; verified `logs` is blocked while `logs_backup` is allowed |
| Broad workspace | `/` or the user's home as workspace is too broad for this read-only Agent | Rejects root and the current user's home directory as workspace root; home subprojects remain allowed |
| Search traversal | Candidate collection built and sorted the whole tree before applying visit/time limits | Search now traverses incrementally and skips excluded directories/symlinks without descending into them |
| Search completeness | `max_results` could stop early while reporting `search_complete=true` | Limit stops now set `search_complete=false` with a skipped reason |
| Log save | Record was written, then truncated/rewritten to add `log_path`; a later failure could desync returned status and disk | Log path is fixed before serialization and written once through a same-directory temp file and no-clobber hard link |
| Log status | Log write failure changed execution status to `log_write_failed` | Execution `status` and `persistence_status` are separated; exit code is nonzero if persistence fails |
| Failed model request | Failed `/api/chat` request payload could be missing from run steps | Failed model request attempts now preserve the outgoing payload snapshot and error record when the client exposes it |
| HTTP error classification | HTTP 4xx/5xx could be reported as generic connection failure | HTTPError is handled before URLError and includes a bounded response body in local diagnostics |
| Incomplete generation | `done=false` or `done_reason=length` could still become `completed` | Such responses now end as `incomplete_model_response` |
| Context budget | File byte limits were distinct from model context but no conservative payload limit existed | Added a conservative payload byte limit before model calls; it is not reported as a token guarantee |
| Product event coupling | `agent-read` argument failures could write product `events.jsonl` through common CLI exception handling | `agent-read` failures no longer call product `log_event` |
| Demo scorer | Old scorer combined answer and evidence text, allowing contradictions to pass | Scorer v2 separates evidence checks from final-answer checks for the fixed synthetic cases |

## Reproduced but intentionally not expanded

- A policy violation in a mixed batch still rejects the whole batch and executes zero calls. This is preserved.
- Single-call tool errors may still allow a later model turn to recover, matching the previous design.
- `completed` remains an execution state: tool-backed final answer reached. It is not a semantic correctness certificate.
- Exact tokenizer accounting was not introduced. The new `MAX_MODEL_PAYLOAD_BYTES` is a conservative byte guard only.
- Page reading, larger context, write/shell/Git tools, and new Agent framework were not added.

## Files changed

- `job_agent/readonly_agent.py`
  - strengthened path policy, search traversal/completeness, logging, HTTP error handling, payload recording, incomplete response checks, context payload guard.
- `job_agent/__main__.py`
  - avoids product `events.jsonl` logging for `agent-read` failures handled by the CLI exception path.
- `eval/run_agent_phase1_cli_demo.py`
  - adds scorer v2 and preserves partial runner results after each case.
- `tests/test_readonly_agent.py`
  - adds direct policy, logging, failed request, incomplete generation, and search limit tests.
- `tests/test_agent_phase1_demo_runner.py`
  - adds scorer regression tests for contradictory boolean and no-match answers.
- `README.md`, `eval/README.md`, `HANDOFF.md`, `eval/adr_readonly_workspace_agent_2026-10-06.md`
  - document current guarantees and handoff state.

## Offline verification

| Command/check | Result |
|---|---|
| `python -m unittest tests.test_readonly_agent tests.test_agent_phase1_demo_runner -v` | 26/26 passed |
| `python -m unittest discover -s tests -v` | 94/94 passed |
| APFS/case path check with synthetic `.env` and `LOGS` paths | `.ENV` and `LOGS/secret.txt` blocked; `logs_backup/public.txt` allowed |
| Synthetic marker leak check | excluded marker was not present in model logs or search results |
| Context payload guard | 200k-character synthetic question ended as `context_budget_exceeded` with 0 model attempts |
| `agent-read` invalid workspace with temp `--db` | returned 1 and did not create `events.jsonl` |

## Offline re-score of prior Phase 1 outputs

Saved to `eval/agent_phase1_cli_rescore_phase12_2026-10-06.json`.

| Existing file | Old passed | New scorer v2 passed | Note |
|---|---:|---:|---|
| `eval/agent_phase1_cli_demo_results_rerun_2026-10-05.json` | 5/6 | 5/6 | Preserves old failure for multi-call case |
| `eval/agent_phase1_cli_demo_results_phase11_2026-10-06.json` | 6/6 | 6/6 | New scorer still accepts the Phase 1.1 run |

The re-score is not a new model run.

## Limited local model check

A separate synthetic workspace was created at `eval/agent_phase12_model_workspace_2026-10-06`. It contains only synthetic files plus a synthetic excluded `.ENV` marker.

- Result JSON: `eval/agent_phase12_model_results_2026-10-06.json`
- Report: `eval/agent_phase12_model_report_2026-10-06.md`
- Logs: `eval/agent_phase12_model_logs_2026-10-06/`

Model/run settings:

- Model: `qwen3:4b-instruct-2507-q4_K_M`
- Digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- Ollama: `0.34.4`
- Quantization: `Q4_K_M`
- Options: `temperature=0`, `num_ctx=4096`, `num_predict=768`, `think=false`
- Ollama was started for this check only and stopped afterward.

| Case | Status | Result |
|---|---|---|
| `phase12_read_false` | `completed` | read `settings/app.json`, final answer said `enabled=false` |
| `phase12_search_code` | `completed` | searched `src/report.py`, found `CODE_RED` |
| `phase12_batch_two_files` | `completed` | executed two `read_file` calls in one model turn and answered `Project Helio` |
| `phase12_no_match` | `completed` | searched `docs`, no matches, final answer reported no match |
| `phase12_excluded_env` | `policy_or_tool_error` | model requested `.ENV`; batch prevalidation rejected it; tool execution attempts 0 |

Summary: 5 cases, 4 completed, 1 intended policy error, 9 model attempts/responses, prompt/output tokens 10940/306, Agent internal elapsed 6295.302 ms. The synthetic excluded marker did not appear in any saved log.

## Not verified or not guaranteed

- SIGKILL, power loss, and filesystem failure in the middle of the final log write are not fully recoverable. The implementation avoids the previous second truncate/write and exposes persistence failure, but does not implement a full event journal.
- Exact model tokenizer budget is not computed.
- Real user projects, user documents, product DBs, OCR image assets, and private home secrets were not opened.
- A large benchmark was not run. The local model check is a small representative regression, not a general Agent benchmark.
- Write/shell/Git tools remain unapproved and unimplemented.
