# ADR: keep the job tool and add a bounded read-only workspace Agent

Date: 2026-10-06

## Context

The project started as a local AI Job Agent for job posting management, OCR input, document search, and local JD/evidence analysis. Later user requests explicitly explored whether it could become a Codex-like local tool-using Agent. Phase 1 implemented a limited read-only CLI Agent over a user-selected workspace.

The Phase 0 document remains a historical design note. It should not be rewritten as if it described the current workspace Agent. The current direction is based on later user approval and audit work.

## Decision

Keep the existing job/OCR/analysis functions, and maintain the read-only workspace Agent as a separate CLI path, `agent-read`. The read-only Agent exposes only `list_files`, `read_file`, and `search_text`, bounded by a user-specified workspace and local Ollama native tool calling.

## Current guarantees

- No file write/delete/shell/Git tools are exposed to the model.
- Workspace paths must be relative; absolute paths, `..`, symlinks, excluded names/patterns, representative sensitive paths, root, and the user's home directory as workspace are rejected.
- Logs are local JSON files and may include synthetic file content that was actually read. Users should not store real private data in repository logs.
- `completed` means the runtime reached a tool-backed final answer. It does not mean semantic correctness.
- Threat model: the workspace is assumed not to be modified concurrently by an adversary. Path checks are repeated at execution time, which narrows but does not eliminate a time-of-check/time-of-use window (for example, a path replaced by a symlink between check and open).
- Context: chat requests are sent with `truncate=false` (verified on Ollama 0.34.4) and `shift=false` (effect not verified), so an over-long prompt is rejected by the server and recorded as `context_budget_exceeded` instead of older messages being silently dropped. `MAX_MODEL_PAYLOAD_BYTES` is a request-size cap, not a token budget.
- Filesystem error messages returned to the model omit absolute host paths.

## Consequences

The next safe direction is more read-only usability and policy evaluation, not write/shell expansion. File modification tools require a separate design for diff generation, approval, rollback, and stronger persistence guarantees.

## Update 2026-10-06: repository split

The job posting analysis tool and the read-only agent were split into two repositories. This repository (`local-agent-lab`) keeps the agent, its evaluations, and the shared history; the job tool moved to `job-posting-analyzer`. The agent's package was renamed from `job_agent` to `local_agent`, and the CLI became `python -m local_agent`. The decision above (keep the agent bounded and read-only until evaluation supports more) is unchanged.
