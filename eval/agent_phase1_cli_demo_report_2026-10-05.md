# Phase 1 read-only CLI Agent demo

- Fixture: `eval/agent_phase1_cli_demo_cases_2026-10-05.json`
- Workspace: `eval/agent_phase1_demo_workspace_2026-10-05`
- Model: `qwen3:4b-instruct-2507-q4_K_M`
- Log directory: `eval/agent_phase1_cli_run_logs_2026-10-05`

## Summary

- Passed: `0/6`
- Model attempts/responses: `0 / 0`
- Prompt/output tokens: `0 / 0`
- Agent elapsed ms: `31.772`

## Cases

| Case | Expected tools | Actual tools | Status | Passed | Log |
|---|---|---|---|---:|---|
| demo_01_list_root | `['list_files']` | `[]` | ollama_error | N | `eval/agent_phase1_cli_run_logs_2026-10-05/20261005T143949Z-67617bfb.json` |
| demo_02_read_value | `['read_file']` | `[]` | ollama_error | N | `eval/agent_phase1_cli_run_logs_2026-10-05/20261005T143949Z-b2f52f9d.json` |
| demo_03_search_file | `['search_text']` | `[]` | ollama_error | N | `eval/agent_phase1_cli_run_logs_2026-10-05/20261005T143949Z-adea3c53.json` |
| demo_04_search_no_match | `['search_text']` | `[]` | ollama_error | N | `eval/agent_phase1_cli_run_logs_2026-10-05/20261005T143949Z-348a936c.json` |
| demo_05_list_then_read | `['list_files', 'read_file']` | `[]` | ollama_error | N | `eval/agent_phase1_cli_run_logs_2026-10-05/20261005T143949Z-b5d53d92.json` |
| demo_06_read_two_files | `['read_file', 'read_file']` | `[]` | ollama_error | N | `eval/agent_phase1_cli_run_logs_2026-10-05/20261005T143949Z-b31afb67.json` |
