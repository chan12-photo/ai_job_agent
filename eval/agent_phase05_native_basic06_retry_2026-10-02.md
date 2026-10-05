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
| Initial protocol structure | 6/6 | 1/1 |
| Initial tool argument contract | 4/6 | 1/1 |
| Expected tool selected | not separately stored | 0/1 |
| Server policy passed | 4/6 | 1/1 |
| Tool execution ok | 4/6 | 1/1 |
| Requested evidence verified | 2/6 | 0/1 |
| Final answer reached | 4/6 | 0/1 |
| Evidence-grounded final answer | 2/6 | 0/1 |
| Same action repeated | 2/6 | 0/1 |
| Request payload immutability audit | not recorded in custom run | all |
| Generation attempts / responses | 10 / 10 | 2 / 2 |

## Native cases

| Case | Tool | Args | Policy | Execution | Evidence | Final | Answer | Repeat | Attempts |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| basic_06_search_todo_app | list_files | Y | Y | Y | N | N | N | N | 2 |

Full original requests, immutable payloads, server responses, tool arguments, results, tokens, done reasons, and elapsed times are stored in the JSON and SQLite artifacts. This run uses Ollama native `tools` and `message.tool_calls`; it does not use the custom JSON `format` field.
