# Phase 0.5 basic tool-call contract check

- Evaluator version: `phase05-basic6-contract-v2`
- Prompt version: `agent-readonly-json-v2`
- Tool contract version: `readonly-tools-v2`
- Model: `qwen3:4b-instruct-2507-q4_K_M`
- Digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- Runtime: `0.34.4`
- Quantization: `Q4_K_M`
- Options: `{"temperature": 0, "num_ctx": 4096, "num_predict": 768}`
- Ollama reused existing server: `False`

## Corrected previous aggregate

| Metric | Value |
|---|---:|
| Original initial JSON valid | 19/20 |
| Original usable tool and execution | 3/12 |
| Corrected requested evidence verified | 1/12 |
| Corrected final answer reached | 17/20 |
| Second tool call after result | 2/20 |
| Repeated same action | 0/20 |

## New basic 6 summary

| Metric | Value |
|---|---:|
| Initial common format passed | 6/6 |
| Initial protocol contract passed | 6/6 |
| Tool argument contract passed | 4/6 |
| Server policy allowed | 4/6 |
| Tool execution ok | 4/6 |
| Requested evidence verified | 2/6 |
| Final answer reached | 4/6 |
| Final answer correct with tool evidence | 2/6 |
| Generation attempts | 10 |
| Generation responses | 10 |

## Case results

| Case | Tool | Args ok | Evidence | Final | Answer | Attempts |
|---|---|---:|---:|---:|---:|---:|
| basic_01_list_root | list_files | Y | Y | Y | Y | 2 |
| basic_02_list_src | list_files | Y | Y | Y | Y | 2 |
| basic_03_read_readme | None | N | N | Y | N | 1 |
| basic_04_read_config_enabled | None | N | N | Y | N | 1 |
| basic_05_search_todo_workspace | list_files | Y | N | N | N | 2 |
| basic_06_search_todo_app | list_files | Y | N | N | N | 2 |

Direct policy checks verify path, tool, binary, normal text, and prompt-injection-content handling independently of model output.
This run measures a custom JSON protocol passed through Ollama `format`; it is not native tool calling.
