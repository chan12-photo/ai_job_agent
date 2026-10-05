# Phase 1 read-only CLI Agent demo

- Fixture: `eval/agent_phase1_cli_demo_cases_2026-10-05.json`
- Workspace: `eval/agent_phase1_demo_workspace_2026-10-05`
- Model: `qwen3:4b-instruct-2507-q4_K_M`
- Log directory: `eval/agent_phase1_cli_run_logs_rerun_2026-10-05`

## Summary

- Passed: `5/6`
- Model attempts/responses: `12 / 12`
- Prompt/output tokens: `13768 / 422`
- Agent elapsed ms: `8064.705`

## Cases

| Case | Expected tools | Actual tools | Status | Passed | Log |
|---|---|---|---|---:|---|
| demo_01_list_root | `['list_files']` | `['list_files']` | completed | Y | `eval/agent_phase1_cli_run_logs_rerun_2026-10-05/20261005T144022Z-8ea75b5c.json` |
| demo_02_read_value | `['read_file']` | `['read_file']` | completed | Y | `eval/agent_phase1_cli_run_logs_rerun_2026-10-05/20261005T144025Z-3e4454d6.json` |
| demo_03_search_file | `['search_text']` | `['search_text']` | completed | Y | `eval/agent_phase1_cli_run_logs_rerun_2026-10-05/20261005T144025Z-c71d519d.json` |
| demo_04_search_no_match | `['search_text']` | `['search_text']` | completed | Y | `eval/agent_phase1_cli_run_logs_rerun_2026-10-05/20261005T144026Z-95e250e3.json` |
| demo_05_list_then_read | `['list_files', 'read_file']` | `['list_files', 'read_file']` | completed | Y | `eval/agent_phase1_cli_run_logs_rerun_2026-10-05/20261005T144028Z-4291f5b9.json` |
| demo_06_read_two_files | `['read_file', 'read_file']` | `[]` | protocol_error | N | `eval/agent_phase1_cli_run_logs_rerun_2026-10-05/20261005T144029Z-48d4813a.json` |
