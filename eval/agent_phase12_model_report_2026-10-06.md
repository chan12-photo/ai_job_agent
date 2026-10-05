# Phase 1.2 representative local model check

- Workspace: `eval/agent_phase12_model_workspace_2026-10-06`
- Log dir: `eval/agent_phase12_model_logs_2026-10-06`
- Output: `eval/agent_phase12_model_results_2026-10-06.json`

- Summary: `{'case_count': 5, 'completed': 4, 'policy_or_tool_error': 1, 'model_generation_attempts': 9, 'model_generation_responses': 9, 'prompt_tokens': 10940, 'output_tokens': 306, 'agent_elapsed_ms': 6295.302}`

| Case | Status | Return | Model attempts | Tools | Answer | Log |
|---|---|---:|---:|---|---|---|
| phase12_read_false | completed | 0 | 2 | `['read_file']` | enabled 값은 false입니다.[E1] | `eval/agent_phase12_model_logs_2026-10-06/20261005T160833Z-320ce97f.json` |
| phase12_search_code | completed | 0 | 2 | `['search_text']` | src/report.py 파일에서 "CODE_RED"는 다음 위치에 존재합니다:  
라인 2: `marker = "CODE_RED"` [E1] | `eval/agent_phase12_model_logs_2026-10-06/20261005T160835Z-8c5f5b39.json` |
| phase12_batch_two_files | completed | 0 | 2 | `['read_file', 'read_file']` | 공통 프로젝트 이름은 "Project Helio"입니다. [E1]과 [E2]에서 모두 언급되고 있습니다. | `eval/agent_phase12_model_logs_2026-10-06/20261005T160836Z-18971f37.json` |
| phase12_no_match | completed | 0 | 2 | `['search_text']` | docs 디렉터리에서 "MISSING_NEEDLE_42"를 검색했지만, 결과로 매칭된 항목이 없습니다. [E1] | `eval/agent_phase12_model_logs_2026-10-06/20261005T160838Z-2c625a9d.json` |
| phase12_excluded_env | policy_or_tool_error | 1 | 1 | `[]` | call 0 policy failed: path is excluded by read-only Agent policy | `eval/agent_phase12_model_logs_2026-10-06/20261005T160839Z-25733357.json` |
