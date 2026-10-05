# Phase 1.2 후속 보강 보고서 — 감사 프롬프트 미완료 항목 처리

- 날짜: 2026-10-06
- 근거 문서: 사용자가 전달한 `agent_audit_and_repair_prompt.md` 6절(Phase 1.2 실행 프롬프트). Codex가 사용량 소진으로 중단한 작업을 이어받았습니다.
- 범위: 6절이 승인한 범위 안의 보강만 수행했습니다. 도구는 `list_files`, `read_file`, `search_text` 3개를 유지하고 write/shell/Git/UI/새 모델은 추가하지 않았습니다. match-v5, 채용 분석, OCR, DB schema는 건드리지 않았습니다.
- 증거 파일
  - 컨텍스트 시험: [`agent_phase12_context_check_2026-10-06.json`](agent_phase12_context_check_2026-10-06.json) (절대경로 제거)
  - 확인 실행 로그: `agent_phase12_context_logs_2026-10-06/` (git 제외)
  - 재채점 v3: [`agent_phase1_cli_rescore_scorer_v3_2026-10-06.json`](agent_phase1_cli_rescore_scorer_v3_2026-10-06.json)
  - 직전 사용성 평가의 코드 출처 기록: [`agent_phase12_usability_manifest_2026-10-06.json`](agent_phase12_usability_manifest_2026-10-06.json)

## 1. 진단 재검토: 바뀐 판단

이전 턴에서 미완료 항목 8개를 보고했습니다. 수정 전에 각 항목을 실제 조건으로 다시 확인했고, 그 결과 판단이 다음과 같이 바뀌었습니다.

| 항목 | 이전 판단 | 재검토 결과 |
|---|---|---|
| 컨텍스트 예산 | "120KB 상한은 4096 tokens보다 훨씬 커서 무의미하다. Ollama가 조용히 자르는지는 미확인." 해결책으로 클라이언트 측 token 추정을 계획했음 | 실측해 보니 문제가 두 가지였습니다. (a) 마지막 메시지만으로도 넘치는 경우, Ollama는 HTTP 400 `exceed_context_size_error`로 **명시적으로 거부**하지만 런타임은 이를 일반 `ollama_error`로 기록했습니다. (b) 오래된 메시지를 버리면 들어가는 **중간 구간**에서는 Ollama가 기본값으로 메시지를 **조용히 버리고** `done_reason=stop`으로 정상 응답했습니다. 합성 시험에서 질문 메시지가 빠져 모델이 `UNKNOWN`이라고 답했습니다. 바이트 기반 추정으로는 이 구간을 안정적으로 막을 수 없습니다. 그래서 token 추정 대신 서버 truncation을 끄는 방식(`truncate=false`)을 채택했습니다. |
| 배치 중단 기록 | mock으로 Ctrl+C와 OSError를 재현했음 | mock이 없어도 재현됩니다. 권한 없는 디렉터리를 `list_files`하면 단일 호출이어도 `protocol_error`로 끝났고, 해당 호출은 단계 기록에 아예 남지 않았습니다. 이전 판단보다 심각합니다. |
| 채점기 | 인자 미확인, 음성 테스트 부족 | 반대 방향 오류도 있었습니다. 맞는 답인 "true가 아니라 false"를 실패로 채점했습니다. |
| (새로 발견) OS 오류 메시지 | 언급하지 않았음 | `read_file`과 `search_text`의 권한 오류 메시지에 **절대 host 경로**가 들어가 모델 payload로 전달되었습니다. 직전에 고친 symlink 절대경로 문제와 같은 종류입니다. |

## 2. 수정 내역과 검증

수정한 각 항목에는 회귀 테스트를 붙였습니다. 새 런타임 테스트 7개는 **수정 전 코드(직전 사용성 평가 때의 코드, sha256 `8cb6dcf6…`)에서 모두 실패하고 수정 후 통과**하는 것을 별도 복사본에서 확인했습니다.

| # | 문서 항목 | 수정 | 테스트 |
|---|---|---|---|
| 1 | D3·D4·D5 | `/api/chat`에 `truncate=false`와 `shift=false`를 추가했습니다. HTTP 400 `exceed_context_size_error`를 `ContextLimitError`로 구분해 `context_budget_exceeded`로 기록하고, `n_prompt_tokens`와 `n_ctx`를 남깁니다. `MAX_MODEL_PAYLOAD_BYTES`는 "요청 크기 상한, token 예산 아님"으로 의미를 바로잡았습니다. 이미 읽은 근거는 보존됩니다. | `test_native_payload_disables_server_side_truncation`, `test_context_size_http_400_ends_as_context_budget_exceeded_with_evidence` |
| 2 | C6·C7 | 배치 실행 중 예외가 나면 진행 중이던 호출(`executed=true`, `execution_error`)과 시작하지 못한 호출(`skipped_after_interruption`)을 기록한 뒤 예외를 다시 올립니다. KeyboardInterrupt를 삼키지 않습니다. `proposed_tool_calls`는 모델이 실제로 낸 호출 수로 셉니다. `failed_tool_executions`와 `skipped_tool_calls`를 추가했습니다. `outcome=None`인 단계도 안전하게 처리합니다. | `test_interrupt_mid_batch_records_inflight_and_skipped_calls` (제안 3, 시작 2, 성공 1, 실패 1, 건너뜀 1) |
| 2b | C7 | 파일시스템 OSError는 `protocol_error`가 아닌 도구 오류로 처리합니다. 읽을 수 없는 디렉터리의 `list_files`가 이에 해당합니다. | `test_unreadable_directory_listing_is_tool_error_not_protocol_error` |
| 3 | C4 | 로그 저장에 실패하면 `log_path`를 비우고 시도한 경로는 `log_error`에 적습니다. 직렬화 실패도 저장 실패로 처리합니다. 저장 실패 경고는 `--json` 모드에서도 stderr로 출력합니다. | `test_log_write_failure_does_not_report_unsaved_path`, `test_log_serialization_failure_is_reported` |
| 3b | B7 (새로 발견) | OS 오류 메시지를 `PermissionError: Permission denied`처럼 경로 없이 기록합니다(read/list/search 전부). | `test_os_errors_do_not_expose_absolute_paths` |
| 4 | 4절 6번 | `validate_for_execution` 주석의 "cannot bypass"를 "줄이지만 제거하지 않음"으로 고쳤습니다. ADR에 위협 모델을 명시했습니다. | (문서) |
| 5 | E2·E4·E5·E6 | Phase 1 데모 scorer를 v3로 올렸습니다. 검색 query/path 인자를 확인하고, 참·거짓이 둘 다 나오는 boolean 답은 "수동 검토 필요"(None)로 분류해 합격으로 세지 않습니다. 결과 manifest에 코드 sha256을 넣었습니다. | 음성 테스트 6개 추가: 잘못된 파일 검색, 잘못된 query/path의 no-match, 불완전 검색의 "없음" 답, 부정문 2종, 수동 검토의 합격 미집계, 구형 기록 호환 |
| 6 | G2 | Phase 0 문서 맨 위에 "역사적 문서" 표시만 추가했습니다. 본문은 그대로입니다. | (문서) |
| 7 | G3 | `.gitignore`에 `eval/agent_*_logs_*/`를 추가해 절대경로가 든 로그 폴더 3종을 git에서 제외했습니다. | `git check-ignore` 확인 |
| 8 | G4 | Phase 1 데모 runner와 사용성 runner의 결과에 코드 sha256을 기록합니다. 이미 끝난 사용성 평가에는 별도 manifest를 남겼습니다(실행 후, 코드 변경 전에 계산). | — |

### 작업 중 제가 만든 오류 (보고 전에 바로잡음)

- **scorer v3 첫 재채점 결과가 틀렸습니다.** 2026-10-05 rerun 결과가 5/6에서 3/6으로 떨어졌는데, 원인은 모델이 아니라 제 채점기였습니다. Phase 1 초기 기록에는 `executed` 필드가 없는데, 인자 검사가 `executed is True`인 단계만 보는 바람에 실제로는 맞는 인자(`CODE_RED @ src/report.py`)를 0건으로 읽었습니다. `tool_sequence`와 같은 규칙(`executed is not False`)으로 고치고 구형 기록 테스트를 추가했습니다. 방금 만든 잘못된 출력 파일은 지우고 다시 생성했습니다. 기존 입력 파일 3개의 sha256이 바뀌지 않은 것도 확인했습니다.
- **컨텍스트 회귀 테스트 설계 오류:** 처음 작성한 테스트에서 가짜 응답이 `prepare_metadata`의 `/api/tags` 요청에 먼저 소비되었습니다. 테스트 구성을 고쳤고 런타임 코드는 바꾸지 않았습니다.
- **`shift` 시험은 결론을 내지 못했습니다.** prompt를 2625 tokens로 잡아 한도(4096)에 도달하지 않았습니다. 성공할 때까지 반복하지 않고 "미검증"으로 기록했습니다.

## 3. 실제 모델 확인 (총 /api/chat 11회, 서버 로그로 확인)

환경: Ollama 0.34.4, `OLLAMA_NO_CLOUD=1`, `127.0.0.1:11434`, 진단용 `OLLAMA_DEBUG=1`. 모델과 digest는 기존과 동일합니다. 옵션은 `temperature=0`, `num_ctx=4096`, `num_predict=768`, `think=false`로 바꾸지 않았습니다. Ollama는 꺼져 있던 것을 제가 시작했고, 종료 시 제가 시작한 PID 14157만 끝냈습니다.

| 시험 | 요청 수 | 결과 |
|---|---:|---|
| 수정 전, 10,207 bytes 숫자 파일 읽기 Agent 실행 | 2 | 2턴이 HTTP 400(10815 > 4096 tokens)으로 끝났지만 상태는 **`ollama_error`** 였습니다. |
| 수정 전, 같은 내용을 단일 요청으로 | 1 | HTTP 400 (10688 tokens) |
| 서버 truncation 중간 구간, 기본값 | 1 | **성공처럼 응답**: prompt_eval_count 3542(원래 4772), `done_reason=stop`, 답 `UNKNOWN`. 질문 메시지가 조용히 빠졌습니다. |
| 같은 요청, `truncate=false` | 1 | HTTP 400 `exceed_context_size_error`, `n_prompt_tokens=4772` |
| `shift` 기본값 / `false` | 2 | 둘 다 eval 768, `length`. 한도에 도달하지 않아 **결론 없음** |
| 수정 후 CLI, 작은 파일 | 2 | `completed`, 답 42 [E1]. 모든 payload에 `truncate=false`와 `shift=false`가 들어 있고 정상 동작에 지장이 없었습니다. |
| 수정 후 CLI, 큰 파일 | 2 | **`context_budget_exceeded`**, "prompt 10882 tokens exceeds num_ctx 4096", 근거(read_file 10207 bytes) 보존, 종료 코드 1, 로그 저장됨 |

## 4. 재채점 (오프라인, 모델 호출 없음)

| 결과 파일 | 원래 판정 | v2 재채점 | v3 재채점 |
|---|---:|---:|---:|
| `agent_phase1_cli_demo_results_rerun_2026-10-05.json` | 5/6 | 5/6 | 5/6 |
| `agent_phase1_cli_demo_results_phase11_2026-10-06.json` | 6/6 | 6/6 | 6/6 |

v3에서 수동 검토로 분류된 사례는 0건입니다. 기존 파일은 수정하지 않았습니다.

## 5. 테스트

| 시점 | 결과 |
|---|---|
| 이번 작업 시작 시 | 104/104 |
| 수정 후 `python -m unittest discover -s tests -v` | **117/117 통과** (104 + 런타임 7 + scorer 6) |
| 새 런타임 회귀 테스트 7개를 수정 전 코드에 실행 | 7개 모두 실패 (결함 재현 확인) |

## 6. 지금 보장하는 것과 보장하지 않는 것

보장하는 것 (테스트 또는 실측 근거가 있음):
- 현재 설정에서 prompt가 `num_ctx`를 넘으면 서버가 거부하고, 런타임은 `context_budget_exceeded`와 정확한 token 수를 남깁니다. 오래된 메시지가 조용히 빠지는 일은 0.34.4에서 막혔습니다.
- 배치 중 Ctrl+C가 나도 앞선 성공 결과, 중단된 호출, 시작하지 못한 호출이 구분되어 로그에 남습니다.
- 파일시스템 오류 메시지에는 절대경로가 들어가지 않습니다.
- 로그 저장에 실패하면 존재하지 않는 경로를 보고하지 않고, 종료 코드 1과 stderr 경고를 냅니다.

보장하지 않는 것:
- `shift=false`의 효과(미검증). 다만 출력 한도에 걸리면 기존대로 `done_reason=length`를 `incomplete_model_response`로 처리합니다.
- Ollama의 다른 버전에서의 truncation 동작. `runtime_version`이 기록되므로 버전이 바뀌면 재확인이 필요합니다.
- 큰 파일 처리. 현재 설정(4096 tokens)에서는 기본 읽기 한도 12,000 bytes 안의 파일이라도 token이 많으면 다음 모델 호출이 `context_budget_exceeded`로 끝납니다. 페이지 읽기는 별도 계획이 필요합니다.
- 다른 프로세스가 workspace를 동시에 바꾸는 상황에 대한 TOCTOU 방어, SIGKILL이나 전원 차단 시 로그 보존, hard link를 지원하지 않는 파일시스템(예: exFAT)에서의 로그 저장(이 경우 저장 실패로 보고됨).

## 7. 변경 파일

수정한 기존 파일:
- `job_agent/readonly_agent.py`: 1, 2, 2b, 3, 3b, 4번 항목
- `tests/test_readonly_agent.py`: 회귀 테스트 7개
- `eval/run_agent_phase1_cli_demo.py`: scorer v3, 코드 sha256
- `tests/test_agent_phase1_demo_runner.py`: 음성 테스트 6개
- `eval/run_agent_phase12_usability.py`: 코드 sha256 기록
- `README.md`: 종료 상태 목록 정정(`context_budget_exceeded`, `incomplete_model_response` 추가, `log_write_failed` 설명), 컨텍스트 동작, 로그 git 제외 안내
- `eval/adr_readonly_workspace_agent_2026-10-06.md`: 위협 모델, 컨텍스트, 오류 메시지 보장
- `AI_Job_Agent_Phase0_2026-09-29.md`: 맨 위 역사적 문서 표시만 추가
- `.gitignore`: `eval/agent_*_logs_*/`
- `HANDOFF.md`, `eval/README.md`: 이번 후속 내용 추가

새 파일:
- `eval/rescore_agent_phase1_demo.py`
- `eval/agent_phase1_cli_rescore_scorer_v3_2026-10-06.json`
- `eval/agent_phase12_context_check_2026-10-06.json`
- `eval/agent_phase12_context_logs_2026-10-06/` (2개, git 제외)
- `eval/agent_phase12_usability_manifest_2026-10-06.json`
- `eval/agent_phase12_followup_report_2026-10-06.md` (이 문서)

기존 Phase 1.2 보고서의 "conservative payload byte limit" 서술은 원본 보존을 위해 고치지 않았습니다. 이 보고서와 README·ADR·HANDOFF에서 정정했습니다.

## 8. 남은 일과 다음 단계

- 감사 프롬프트 6절의 필수 항목은 이번으로 모두 처리했습니다. 남은 것은 위 "보장하지 않는 것"에 적은 범위 제한입니다.
- 직전 사용성 평가에서 남은 두 문제는 여전히 사용자 결정이 필요합니다. (1) 파일 속 지시를 모델이 따르는 문제(u12). (2) 정책상 건너뛴 파일을 불완전 검색으로 보는 기준(u07).
- write/shell 도구 검토는 아직 권하지 않습니다.
