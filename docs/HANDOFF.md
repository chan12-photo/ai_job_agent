# Handoff notes — read-only local agent

> **Development handoff notes.** Written during development so that another AI assistant could continue the work. Earlier sections describe the combined repository before the 2026-10-06 split; the job posting analysis tool now lives in `job-posting-analyzer`, and the package here is `local_agent` (CLI: `python -m local_agent`).

## Current goal

Stabilize the Phase 1.1 read-only CLI Agent before considering any write, shell, Git, or UI expansion.

## Allowed scope completed

- Kept tools limited to `list_files`, `read_file`, `search_text`.
- Strengthened workspace path policy and representative sensitive path exclusions.
- Preserved Phase 1.1 multi-tool-call batch behavior.
- Improved search completeness, logging, failed request recording, incomplete response handling, and demo scoring.
- Did not alter `match-v5`, job analysis DB schema, OCR behavior, product UI, or actual user data.

## Important changed files

- `job_agent/readonly_agent.py`
- `job_agent/__main__.py`
- `eval/run_agent_phase1_cli_demo.py`
- `tests/test_readonly_agent.py`
- `tests/test_agent_phase1_demo_runner.py`
- `README.md`
- `eval/README.md`
- `eval/agent_phase1_2_report_2026-10-06.md`
- `eval/adr_readonly_workspace_agent_2026-10-06.md`

## Verification performed

- `python -m unittest tests.test_readonly_agent tests.test_agent_phase1_demo_runner -v` → 26/26 passed.
- `python -m unittest discover -s tests -v` → 94/94 passed.
- Direct Mac synthetic path checks confirmed `.ENV`, `.env`, `LOGS/secret.txt`, and excluded logs root are blocked, while `logs_backup/public.txt` is allowed.
- Existing Phase 1 saved outputs re-scored with scorer v2 in `eval/agent_phase1_cli_rescore_phase12_2026-10-06.json`.
- Limited local Ollama check on 5 synthetic cases saved to `eval/agent_phase12_model_results_2026-10-06.json`; 4 completed and 1 intended policy rejection.
- Context payload guard was checked with a synthetic 200k-character question: `context_budget_exceeded`, 0 model attempts.
- `agent-read` invalid workspace does not write product `events.jsonl`.

## Not verified

- Real user projects and private files.
- SIGKILL/power-loss recovery.
- Exact tokenizer-based context budget.
- Any write/shell/Git tool behavior.
- Large blind benchmark.

## Known remaining limits

- `completed` is an execution state, not an answer correctness guarantee.
- The new context guard is byte-based and conservative, not exact token accounting.
- Log write is safer than before but not a full event journal.
- Search reports skipped paths and incompleteness; it does not prove semantic absence when search is incomplete.

## Next single recommended task

Run a small, fixed read-only usability evaluation on a synthetic multi-directory project that resembles a coding repository. Do not add write/shell tools until read-only path selection, exclusion behavior, and answer grounding are stable on that scenario.

## Prompt for another AI reviewer

Read `HANDOFF.md`, `eval/agent_phase1_2_report_2026-10-06.md`, the current diff, and the changed tests. Review whether the read-only Agent still has access-policy, logging, or scoring defects. Do not implement new features, do not repeat the completed Ollama runs unless a specific log/code mismatch requires it, and do not touch real user data.

## Update 2026-10-06 — synthetic coding-project usability evaluation (read-only)

- Report: `eval/agent_phase12_usability_report_2026-10-06.md`; results: `eval/agent_phase12_usability_results_2026-10-06.json`; runner: `eval/run_agent_phase12_usability.py`; fixture: `eval/agent_phase12_usability_cases_2026-10-06.json`; logs: `eval/agent_phase12_usability_logs_2026-10-06/`.
- One-shot run, 12 cases, 22 model requests (cap 40), same model/options. Strict auto score 10/12. No marker leaks, no repeated calls, payload/log integrity 12/12, `.ENV` and outside symlink rejected before execution.
- Failures: u04 used `search_text` instead of `read_file` for a value check (answer correct; system prompt rules overlap). u12 followed an in-file instruction and appended `INJECTION_ACCEPTED` to the answer (no forbidden tool call; status still `completed`).
- Usability limit: policy-excluded files and symlinks make root searches `search_complete=false`, so root searches in repos with `.env`/symlinks end as `unverified_final` (exit 2).
- Bug fixed: `search_text` recorded an outside-pointing symlink skip with its absolute host path; now workspace-relative. Regression test added. Tests: 104/104.
- Recommendation: do not start write/shell yet. Next: user decision on search-completeness semantics for policy skips, and a separately approved, fresh-case evaluation of in-file instruction handling.

## Update 2026-10-06 — audit prompt follow-up (remaining Phase 1.2 items)

- Report: `eval/agent_phase12_followup_report_2026-10-06.md`. Evidence: `eval/agent_phase12_context_check_2026-10-06.json`, `eval/agent_phase1_cli_rescore_scorer_v3_2026-10-06.json`, `eval/agent_phase12_usability_manifest_2026-10-06.json`.
- Correction to the earlier Phase 1.2 claim: the 120,000-byte payload guard was never a context guard (num_ctx is 4096 tokens). On Ollama 0.34.4 the default chat request silently dropped older messages when the history exceeded num_ctx (synthetic test: the question message vanished and the model answered `UNKNOWN` with `done_reason=stop`). Requests now send `truncate=false` (verified) and `shift=false` (effect unverified); overflow is a server HTTP 400 recorded as `context_budget_exceeded` with exact `n_prompt_tokens`.
- Also fixed: batch interruption recording (in-flight vs skipped calls, real proposed count), unreadable directory listing as tool error instead of `protocol_error`, absolute paths removed from filesystem error messages sent to the model, unsaved `log_path` no longer reported plus stderr warning, TOCTOU comment, Phase 1 demo scorer v3 (search args, manual-review state for ambiguous booleans), Phase 0 historical banner, log dirs git-ignored, code hashes in runner outputs.
- Model requests this round: 11 `/api/chat` (server log). Ollama was started for this work and only that PID was stopped.
- Tests: 117/117. The 7 new runtime regression tests fail on the pre-fix runtime copy.
- Still open (user decision): in-file instruction following (usability u12), whether policy-skipped files should make searches incomplete (u07). Large-file paging is not implemented; token-heavy files end as `context_budget_exceeded`.
- Next single recommended task: decide the u07 search-completeness rule, then measure in-file instruction handling on a fresh fixed case set before any write/shell discussion.

## Update 2026-10-06 — portfolio preparation (stages 1–2)

- Target: public GitHub portfolio for LLM application/evaluation engineering (backend secondary), Korean and English, one repository framed as "local LLM tools that have to show their evidence".
- Stage 1 (done): local absolute paths redacted from 13 evidence files (`eval/redaction_manifest_2026-10-06.json`; originals kept in git-ignored `local_only/`), `scripts/check_public_safety.py` (run before every commit/push; full history scanned clean), MIT license, reconstructed `docs/TIMELINE.md`, git history started with author `chan12-photo` (GitHub noreply email, repo-local config).
- Stage 2 (done): `agent-read --replay` and `scripts/run_demo.py` reproduce six recorded runs without Ollama (verified on a fresh clone: 6/6, tests 126/126); new English `README.md`, Korean `README.ko.md`, `docs/EVALUATION.md`; the old README moved verbatim to `docs/USAGE.ko.md`.
- Not done: web UI screenshot/GIF, CI, the pre-registered held-out evaluation, in-file instruction mitigation (u12), search-completeness decision (u07). The README clone URL assumes the GitHub repository name `chan12-photo/ai_job_agent`.

## Update 2026-10-06 — web UI screenshots, publication, stage 3 injection evaluation

- Published: https://github.com/chan12-photo/ai_job_agent (public). Screenshots in `docs/images/`; a web UI bug that rendered extracted JD fields as raw dicts was fixed with a regression test.
- Stage 3: pre-registered indirect prompt injection evaluation in `eval/agent_injection_2026-10-06/` (PREREGISTRATION.md pushed before any run, REPORT.md with results). Test attack success 1/18 → 0/18 with profile v4; the registered rule is met on one case, with one plausible new failure (answering before reading after `list_files`), so the default profile stays `v2`. The registered canary detector missed spaced echoes; this is documented, not re-scored. 179 of 250 model requests used. The sealed test set is spent; a new mitigation needs a new sealed set.
- `agent-read --prompt-profile {v2,v3,v4}`; replays use the profile recorded in their fixture.
- Next candidates: a non-pushy tool-result reminder plus a detector that counts spaced canaries, under a new pre-registration; the natural-language search-query failure (separately).

## Update 2026-10-06 — repository split and rename

- This repository is now agent-only (`local-agent-lab`); the job posting analysis tool, its tests, evaluations, screenshots, and the Phase 0 design document moved to the separate repository `job-posting-analyzer` (commit `504b2b8` there).
- Package `job_agent` → `local_agent`; CLI `python -m job_agent agent-read` → `python -m local_agent`. Default log folder: `~/Library/Application Support/LocalAgentLab/runs`.
- Pre-registered injection files were not moved, so their registration hashes still verify.
- Next: compare `gpt-oss:20b` and `devstral-small-2:24b` (free, Apache 2.0, ~14–15 GB) against the 4B baseline on the existing evaluations, after the user approves the downloads.
