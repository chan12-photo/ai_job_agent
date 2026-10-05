# Phase 0.5 custom JSON versus native Ollama tool calling

- Evaluator: `phase05-native-basic6-v1`
- Prompt: `agent-readonly-native-v1`
- Tool contract: `readonly-tools-v2-native`
- Model: `qwen3:4b-instruct-2507-q4_K_M`
- Digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- Runtime: `0.34.4`
- Quantization: `Q4_K_M`
- Options: `{"temperature": 0, "num_ctx": 4096, "num_predict": 768}`
- Existing basic6 summary matches saved JSON: `True`

## Comparison summary

| Metric | Custom JSON basic6 | Native tool calling |
|---|---:|---:|
| Initial protocol structure | 6/6 | 6/6 |
| Initial tool argument contract | 4/6 | 6/6 |
| Expected tool selected | not separately stored | 5/6 |
| Server policy passed | 4/6 | 6/6 |
| Tool execution ok | 4/6 | 6/6 |
| Requested evidence verified | 2/6 | 5/6 |
| Final answer reached | 4/6 | 5/6 |
| Evidence-grounded final answer | 2/6 | 5/6 |
| Same action repeated | 2/6 | 0/6 |
| Request payload immutability audit | not recorded in custom run | 6/6 |
| Generation attempts / responses | 10 / 10 | 12 / 12 |

## Native cases

| Case | Tool | Args | Policy | Execution | Evidence | Final | Answer | Repeat | Attempts |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| basic_01_list_root | list_files | Y | Y | Y | Y | Y | Y | N | 2 |
| basic_02_list_src | list_files | Y | Y | Y | Y | Y | Y | N | 2 |
| basic_03_read_readme | read_file | Y | Y | Y | Y | Y | Y | N | 2 |
| basic_04_read_config_enabled | read_file | Y | Y | Y | Y | Y | Y | N | 2 |
| basic_05_search_todo_workspace | search_text | Y | Y | Y | Y | Y | Y | N | 2 |
| basic_06_search_todo_app | list_files | Y | Y | Y | N | N | N | N | 2 |

Full original requests, immutable payloads, server responses, tool arguments, results, tokens, done reasons, and elapsed times are stored in the JSON and SQLite artifacts. This run uses Ollama native `tools` and `message.tool_calls`; it does not use the custom JSON `format` field.
