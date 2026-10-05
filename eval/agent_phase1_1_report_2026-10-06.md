# Phase 1.1 읽기 전용 CLI Agent 순차 tool call 처리 검증

## 범위

이번 작업은 Phase 1의 읽기 전용 CLI Agent에서 Ollama native `message.tool_calls`가 한 assistant 응답에 여러 개 들어오는 경우를 처리하기 위한 최소 확장이다. 파일 수정·삭제·셸·Git 도구, 웹 UI, 채용 분석 로직, OCR, 제품 DB는 변경하지 않았다.

허용 도구는 기존과 같이 `list_files`, `read_file`, `search_text` 세 개다. 모델 생성 요청 최대 4회, 도구 실행 최대 3회, 기본 전체 시간 180초 제한을 유지했다.

## 기존 실패 원인

기존 Phase 1 실제 재실행 결과는 `5/6`이었다.

- 결과 파일: `eval/agent_phase1_cli_demo_results_rerun_2026-10-05.json`
- 보고서: `eval/agent_phase1_cli_demo_report_rerun_2026-10-05.md`
- 실패 로그: `eval/agent_phase1_cli_run_logs_rerun_2026-10-05/20261005T144029Z-48d4813a.json`

실패 사례 `demo_06_read_two_files`에서 모델은 다음 두 호출을 같은 assistant 응답에 반환했다.

1. `read_file({"path":"docs/alpha.md","max_bytes":32768})`
2. `read_file({"path":"docs/beta.md","max_bytes":32768})`

두 호출은 모두 요청한 파일을 읽는 유효한 `read_file` 호출이었고, 금지 경로·중복 호출은 없었다. 실패 이유는 기존 CLI가 한 응답에 정확히 하나의 tool call만 허용했기 때문이다. 따라서 이번 변경은 모델의 잘못된 프로토콜을 고친 것이 아니라, Ollama native tool calling 응답 형식에서 가능한 여러 호출을 지원하는 범위 확장이다.

Ollama 공식 `/api/chat` 문서는 assistant 응답의 `message.tool_calls` 배열을 native 도구 호출 구조로 설명한다. 이번 구현은 기존 런타임에서 동작하던 `role=tool`, `tool_name` 후속 메시지 형식을 유지했고, OpenAI 전용 필드를 추정해 추가하지 않았다.

## 구현 요약

수정 파일:

- `job_agent/readonly_agent.py`
  - `PROMPT_VERSION`을 `readonly-cli-agent-v2`로 올렸다.
  - 독립적인 여러 파일 읽기는 한 응답의 여러 `read_file` 호출로 허용한다고 안내했다.
  - `parse_native_tool_calls()`를 추가해 여러 native tool call을 구조화한다.
  - `ReadOnlyWorkspace.validate_for_execution()`을 추가해 파일 본문 조회나 검색 실행 전에 인자·경로 정책을 검사한다.
  - 한 응답의 모든 호출을 사전 검증한 뒤, 모두 통과할 때만 순서대로 실행한다.
  - 예산 초과, 금지 경로, 인자 계약 실패, 묶음 안 중복, 이전 행동 반복이 하나라도 있으면 해당 묶음은 실행 0회로 종료한다.
  - 실제 실행에서도 기존 `policy_and_execute()` 검증을 다시 수행한다.
  - 호출별 `model_turn`, `call_index`, `call_id`, 원래 인자, 검증 후 인자, 실행 여부, 결과, 스킵 사유를 기록한다.
  - `proposed_tool_calls`, `tool_execution_attempts`, `successful_tool_executions`를 구분해 기록한다.

- `tests/test_readonly_agent.py`
  - 기존 “여러 tool call이면 항상 protocol_error” 테스트를 새 계약에 맞게 바꿨다.
  - 같은 응답에서 두 파일 읽기, 서로 다른 도구 두 개, 예산 정확 일치, 예산 초과 실행 0회, 정상+금지 혼합 실행 0회, 묶음 안 중복, 이전 행동 반복, 실행 중 오류, 실행 사이 시간 초과, payload 불변성을 검증했다.

- `eval/run_agent_phase1_cli_demo.py`
  - 실제 실행된 도구만 시연 결과의 도구 순서에 집계하도록 조정했다. 사전 검증에서 차단되어 실행되지 않은 제안 호출은 실행 도구 순서에 섞지 않는다.

- `README.md`, `eval/README.md`
  - Phase 1.1 결과와 재현 명령을 추가했다.

## 사전 검증과 순차 실행 방식

한 assistant 응답에 tool call 묶음이 들어오면 다음 순서로 처리한다.

1. native `tool_calls` 구조를 파싱한다.
2. 남은 도구 실행 예산과 호출 수를 비교한다.
3. 각 호출의 도구 이름, 인자 타입, 필수값, 범위, 추가 필드, workspace 상대 경로 정책을 검사한다.
4. 같은 응답 안의 중복과 이전에 실행한 동일 도구·동일 정규화 인자 반복을 검사한다.
5. 하나라도 실패하면 이번 묶음의 본문 읽기·검색 실행은 0회다.
6. 모두 통과하면 assistant 원본 메시지를 한 번만 대화에 추가한다.
7. 각 호출을 반환 순서대로 실행하고, 호출마다 `role=tool` 결과를 추가한다.
8. 모든 호출이 성공하면 다음 모델 호출을 한 번 수행한다.

실행 도중 오류가 나면 완료된 결과는 기록하고, 실패한 호출과 이유를 남기며, 남은 호출은 실행하지 않았다고 기록한다. 이번 구현에서는 오류가 섞인 여러 호출 묶음 뒤에 unresolved tool call이 남는 후속 요청을 보내지 않는 단순 방식을 사용한다. 단일 tool call 오류의 기존 회복 흐름은 유지했다.

## 자동 검증

`pytest`는 현재 Python 환경에 설치되어 있지 않아 실행하지 않았다. 새 패키지는 설치하지 않았다.

표준 라이브러리 `unittest`로 검증했다.

```sh
python -m unittest tests.test_readonly_agent -v
python -m unittest discover -s tests -v
```

결과:

- `tests.test_readonly_agent`: 18개 통과
- 전체 `tests` 디렉터리: 86개 통과

## 기존 Phase 1과 Phase 1.1 실제 결과 비교

| 실행 | 결과 | 완료 | 도구 순서 일치 | 사실 확인 | 모델 요청/응답 | prompt/output tokens | Agent 내부 소요 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Phase 1, Ollama 꺼짐 | 0/6 | 0/6 | 0/6 | 0/6 | 0/0 | 0/0 | 31.772ms |
| Phase 1, 재실행 | 5/6 | 5/6 | 5/6 | 5/6 | 12/12 | 13768/422 | 8064.705ms |
| Phase 1.1, 이번 실행 | 6/6 | 6/6 | 6/6 | 6/6 | 13/13 | 16080/429 | 8202.224ms |

Phase 1의 Ollama 꺼짐 결과는 사전 연결 확인에서 종료했으므로 모델 생성 요청 0회가 맞다. 기존 원시 결과는 수정하지 않았다.

## Phase 1.1 사례별 결과

| 사례 | 실제 도구 순서 | 상태 | 도구 제안/실행/성공 | 모델 요청 | 판정 |
|---|---|---|---:|---:|---|
| `demo_01_list_root` | `list_files` | `completed` | 1/1/1 | 2 | 통과 |
| `demo_02_read_value` | `read_file` | `completed` | 1/1/1 | 2 | 통과 |
| `demo_03_search_file` | `search_text` | `completed` | 1/1/1 | 2 | 통과 |
| `demo_04_search_no_match` | `search_text` | `completed` | 1/1/1 | 2 | 통과 |
| `demo_05_list_then_read` | `list_files → read_file` | `completed` | 2/2/2 | 3 | 통과 |
| `demo_06_read_two_files` | `read_file → read_file` | `completed` | 2/2/2 | 2 | 통과 |

`demo_06_read_two_files`에서는 첫 모델 턴에 다음 두 호출이 실제로 기록됐다.

1. `read_file({"path":"docs/alpha.md","max_bytes":32768})`
2. `read_file({"path":"docs/beta.md","max_bytes":32768})`

두 결과가 각각 `[E1]`, `[E2]`로 저장됐고 후속 payload의 메시지 순서는 `system,user,assistant,tool,tool`이었다. 최종 답변은 두 파일에 공통으로 등장하는 프로젝트 이름이 `Project Helio`라고 답했고, 두 근거 `[E1]`, `[E2]`를 참조했다.

## 실제 모델·런타임

이번 실제 검증은 이미 설치된 모델만 사용했다.

- 모델: `qwen3:4b-instruct-2507-q4_K_M`
- digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- 형식/양자화: GGUF, `Q4_K_M`
- Ollama: `0.34.4`
- 옵션: `temperature=0`, `num_ctx=4096`, `num_predict=768`, `think=false`
- 서버: `OLLAMA_NO_CLOUD=1`, `OLLAMA_HOST=127.0.0.1:11434`

이번 작업에서 Ollama가 꺼져 있어 새 서버를 시작했고, 검증 후 해당 프로세스만 종료했다.

## 새 산출물

- 결과 JSON: `eval/agent_phase1_cli_demo_results_phase11_2026-10-06.json`
- 요약 보고서: `eval/agent_phase1_cli_demo_report_phase11_2026-10-06.md`
- 상세 로그 디렉터리: `eval/agent_phase1_cli_run_logs_phase11_2026-10-06/`
- 이 보고서: `eval/agent_phase1_1_report_2026-10-06.md`

## 남은 한계

- 이번 실제 6건은 기존 Phase 1 fixture의 재검증이다. 실제 프로젝트 전체나 장기 다회차 Agent 안정성을 뜻하지 않는다.
- 여러 호출 실제 경로는 `demo_06`에서만 확인했다. 다른 조합은 가짜 모델 테스트로 검증했다.
- 파일 수정·삭제·셸·Git 도구는 아직 없다.
- `completed`는 도구 근거가 있는 최종 답변까지 도달했다는 실행 상태다. 답변의 모든 의미를 보증하지 않는다.
- Ollama 문서는 `/api/chat` 응답의 `message.tool_calls` 배열 구조를 명시하지만, 후속 tool result 메시지의 구체 필드는 이번 런타임 payload와 기존 동작으로 확인했다.

## 재현 명령

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve

python eval/run_agent_phase1_cli_demo.py \
  --output /tmp/agent_phase1_1_results.json \
  --report /tmp/agent_phase1_1_report.md \
  --log-dir /tmp/agent_phase1_1_logs
```
