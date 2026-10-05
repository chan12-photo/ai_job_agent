# Phase 0.6-B generalization check

This evaluation uses a synthetic fixture created for Phase 0.6-B. It is informed by the Phase 0.6-A failure mode and is not an independent external benchmark.

## Fixed conditions

- Model: `qwen3:4b-instruct-2507-q4_K_M`
- Digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- Quantization: `Q4_K_M`
- Runtime: `0.34.4`
- Options: `{"temperature": 0, "num_ctx": 4096, "num_predict": 768}`
- Baseline prompt hash: `497d5e1abe206910c0ada34add7e172f40e8f9b9f61e02b373f7391bf0560c09`
- Baseline tools hash: `d864b3645214ea8a6dc85e802d063ec372f6a0e08d0141614ed63b1b1dba2f94`
- Candidate prompt hash: `62d07980645859491a0a4b8b38296c07fb68f1f2eb9dcb92f3515ccbcfd0d8d2`
- Candidate tools hash: `4b82d0e063ee55f166e04dd69f5c6c9ff2e2357a5311ff59c3d62ebb716627a0`
- Phase 0.6-A full reference: `eval/agent_phase06a_candidate_basic6_full_2026-10-05.json`
- Preserved non-reference intermediate: `eval/agent_phase06a_candidate_basic6_2026-10-05.json`

## Summary

| Metric | Baseline | Candidate |
|---|---:|---:|
| Initial tool selected correctly | 8 | 8 |
| Requested path/query matched | 8 | 8 |
| Requested evidence verified | 8 | 8 |
| Evidence-grounded final answer | 8 | 8 |
| Second tool call | 0 | 0 |
| Same action repeated | 0 | 0 |
| Ungrounded final answer | 0 | 0 |
| Tool error misreported as no match | 0 | 0 |
| Generation attempts | 16 | 16 |
| Prompt tokens | 13629 | 17131 |
| Output tokens | 520 | 545 |
| Elapsed ms | 9644.931 | 8871.519 |

## Case comparison

| Case | Baseline tool(args) | Baseline final | Candidate tool(args) | Candidate final |
|---|---|---:|---|---:|
| gen_01_list_root | list_files `{"path": "."}` | Y | list_files `{"path": "."}` | Y |
| gen_02_list_nested | list_files `{"path": "docs/policies"}` | Y | list_files `{"path": "docs/policies"}` | Y |
| gen_03_read_brief_summary | read_file `{"path": "docs/brief.md", "max_bytes": 12000}` | Y | read_file `{"path": "docs/brief.md", "max_bytes": 12000}` | Y |
| gen_04_read_flag_false | read_file `{"path": "settings/flags.json", "max_bytes": 12000}` | Y | read_file `{"path": "settings/flags.json", "max_bytes": 12000}` | Y |
| gen_05_search_file_alpha | search_text `{"query": "ALPHA_PIN", "path": "src/parser.py"}` | Y | search_text `{"query": "ALPHA_PIN", "path": "src/parser.py"}` | Y |
| gen_06_search_dir_shift | search_text `{"query": "SHIFT_CODE", "path": "docs/reports"}` | Y | search_text `{"query": "SHIFT_CODE", "path": "docs/reports"}` | Y |
| gen_07_search_workspace_orbit | search_text `{"query": "ORBIT_NOTE", "path": "."}` | Y | search_text `{"query": "ORBIT_NOTE", "path": ".", "max_results": 20}` | Y |
| gen_08_search_no_match_policy | search_text `{"query": "VANISHING_TOKEN_77", "path": "docs/policies"}` | Y | search_text `{"query": "VANISHING_TOKEN_77", "path": "docs/policies", "max_results": 20}` | Y |

Full payload snapshots, raw server responses, original and normalized tool arguments, tool results, token counts, done reasons, and elapsed times are stored in the JSON and SQLite artifacts.
