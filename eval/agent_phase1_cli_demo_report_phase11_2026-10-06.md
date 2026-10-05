# Phase 1 read-only CLI Agent demo

- Fixture: `eval/agent_phase1_cli_demo_cases_2026-10-05.json`
- Workspace: `eval/agent_phase1_demo_workspace_2026-10-05`
- Model: `qwen3:4b-instruct-2507-q4_K_M`
- Log directory: `eval/agent_phase1_cli_run_logs_phase11_2026-10-06`

## Summary

- Passed: `6/6`
- Model attempts/responses: `13 / 13`
- Prompt/output tokens: `16080 / 429`
- Agent elapsed ms: `8202.224`

## Cases

| Case | Expected tools | Actual tools | Status | Passed | Log |
|---|---|---|---|---:|---|
| demo_01_list_root | `['list_files']` | `['list_files']` | completed | Y | `eval/agent_phase1_cli_run_logs_phase11_2026-10-06/20261005T150915Z-a8877988.json` |
| demo_02_read_value | `['read_file']` | `['read_file']` | completed | Y | `eval/agent_phase1_cli_run_logs_phase11_2026-10-06/20261005T150918Z-1cbb03c0.json` |
| demo_03_search_file | `['search_text']` | `['search_text']` | completed | Y | `eval/agent_phase1_cli_run_logs_phase11_2026-10-06/20261005T150918Z-012599d4.json` |
| demo_04_search_no_match | `['search_text']` | `['search_text']` | completed | Y | `eval/agent_phase1_cli_run_logs_phase11_2026-10-06/20261005T150919Z-861f324d.json` |
| demo_05_list_then_read | `['list_files', 'read_file']` | `['list_files', 'read_file']` | completed | Y | `eval/agent_phase1_cli_run_logs_phase11_2026-10-06/20261005T150921Z-e716e161.json` |
| demo_06_read_two_files | `['read_file', 'read_file']` | `['read_file', 'read_file']` | completed | Y | `eval/agent_phase1_cli_run_logs_phase11_2026-10-06/20261005T150922Z-0ee8ff20.json` |
