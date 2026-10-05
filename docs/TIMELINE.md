# Development timeline / 개발 타임라인

> **Reconstructed, not git history.** This repository had no commits before 2026-10-06. The timeline below is reconstructed from the dated reports and result files in `eval/`, which were written at the time of each step. Every row links to its original evidence. Numbers are copied from those reports; small synthetic sets are regression checks, not general benchmarks.
>
> **재구성한 기록입니다.** 이 저장소는 2026-10-06 이전에 커밋이 없었습니다. 아래 표는 각 단계 당시 작성된 `eval/`의 날짜별 보고서와 결과 파일로 재구성했으며, 모든 행은 원본 증거로 연결됩니다. 숫자는 해당 보고서에서 그대로 옮겼고, 작은 합성 집합은 일반 성능이 아니라 회귀 확인입니다.

## Part 1 — Evidence-grounded job posting analysis / 근거 기반 채용공고 분석

| 날짜 | 단계 | 한 일 | 핵심 결과 | 증거 |
|---|---|---|---|---|
| 2026-09-29 | Phase 0 | 요구사항·위험·아키텍처 설계 검토안 | 구현 전 설계. 현재 구현과 다를 수 있는 역사적 문서 | [Phase 0](../AI_Job_Agent_Phase0_2026-09-29.md) |
| 2026-09-29 | Phase 2 | 검토한 문서의 키워드 검색 기준선 | 가상 질의 Recall@5 6/6. "R을 사용하지 않았습니다"가 검색되는 등 검색 결과 ≠ 자격 증거임을 기록 | [eval/README](../eval/README.md) |
| 2026-09-29 | Phase 3 | 로컬 모델 JD 추출 (1.7B vs 4B) | 4B 형식·원문 인용 4/4지만 의미 정확 3/4. 1.7B는 원문에 없는 연도를 만들어 거부됨 | [phase3_results.json](../eval/phase3_results.json) |
| 2026-09-29 | Phase 4 M1 | JD 추출 → 근거 검색 → 요구별 판정 전체 흐름 | 형식 통과에도 "기록 없음 → 부재로 간주" 과장 발견 | [eval/README](../eval/README.md) |
| 2026-09-30 | match-v3→v5 | 자유 서술 제거, 출력 계약 강화 | 4B `match-v5` 20건: 구조 20/20, 기대 판정 18/20. 같은 계약에서 1.7B는 5/20 | [v5 4B](../eval/phase4_match_v5_results.json), [v5 1.7B](../eval/phase4_match_v5_1p7b_results.json) |
| 2026-09-30 | 전체 흐름 20건 | 사례별 임시 DB에서 전 구간 실행 | 요구별 판정 16/20, 근거 Recall@5 21/21. 단독 18/20과의 차이를 입력 감사로 추적 | [workflow 20](../eval/phase4_workflow_20_results.json) |
| 2026-09-30 | 별도 8건 | 오류 유형을 본 뒤 만든 확인 사례 | `match-v5` 5/8. 개발 중 본 사례이므로 눈가림 평가가 아님을 명시 | [holdout v5](../eval/phase4_match_holdout_v5_results.json) |
| 2026-10-01 | OCR 입력 | macOS Vision OCR + 원본 대조 후 등록 화면 | 가상 이미지에서 오독 유형과 검증 범위 기록 | [ocr_ui](../eval/ocr_ui_2026-10-01.md) |

## Part 2 — Bounded read-only workspace agent / 경계가 있는 읽기 전용 Agent

| 날짜 | 단계 | 한 일 | 핵심 결과 | 증거 |
|---|---|---|---|---|
| 2026-10-01 | Phase 0.5 | 사용자 정의 JSON 도구 호출 가능성 검증 | JSON 형식 20/20이지만 "정확한 도구 + 정책 통과 + 실행 성공"은 4/14 (28.6%) | [phase05 report](../eval/agent_phase05_report_2026-10-01.md) |
| 2026-10-02 | Phase 0.5 | 사용자 정의 JSON vs Ollama native tool calling | 인자 계약 4/6 → 6/6, 정책 통과 4/6 → 6/6. 다른 조건도 달라 인과로 단정하지 않음 | [native basic6](../eval/agent_phase05_native_basic6_report_2026-10-02.md) |
| 2026-10-05 | Phase 0.6 | native 후보 프롬프트 확정(0.6-A)과 신규 사례 일반화 확인(0.6-B) | 신규 8건에서 기존·후보 모두 도구 선택·근거 기반 답변 8/8. 후보의 prompt token이 13629 → 17131로 증가 | [0.6-B](../eval/agent_phase06b_generalization_2026-10-05.md) |
| 2026-10-05 | Phase 1 | `agent-read` CLI (도구 3개, workspace 경계) | 6건 중 5건. 실패는 한 응답에 tool call 2개 → 당시 미지원 | [rerun](../eval/agent_phase1_cli_demo_report_rerun_2026-10-05.md) |
| 2026-10-06 | Phase 1.1 | 한 응답의 여러 tool call을 일괄 사전 검증 후 순차 실행 | 같은 6건 6/6 | [Phase 1.1](../eval/agent_phase1_1_report_2026-10-06.md) |
| 2026-10-06 | 교차 감사 | 다른 AI가 전체 코드·증거를 독립 감사 | `completed` ≠ 정답, 채점기가 틀린 답을 통과시킴, 민감 경로 대소문자 우회 등 | [audit](../eval/review_claude_full_audit_2026-10-06.md) |
| 2026-10-06 | Phase 1.2 | 감사 결과 중 실제 재현된 결함 수정 | 대소문자 우회 차단, 로그 저장 구조, 불완전 응답·검색 판정, scorer v2 | [Phase 1.2](../eval/agent_phase1_2_report_2026-10-06.md) |
| 2026-10-06 | 사용성 평가 | 합성 Python 프로젝트 12건, 1회성 | 엄격 기준 10/12, 차단 대상 실행 0회·유출 0건. 실패: 값 확인에 검색 도구 사용, 파일 속 지시 일부 수행 | [usability](../eval/agent_phase12_usability_report_2026-10-06.md) |
| 2026-10-06 | 후속 보강 | 남은 감사 항목, 실제 Ollama 동작 확인 | Ollama 0.34.4 기본 설정이 `num_ctx` 초과 시 오래된 메시지를 조용히 버림을 재현 → `truncate=false`로 명시적 실패 처리 | [follow-up](../eval/agent_phase12_followup_report_2026-10-06.md), [context check](../eval/agent_phase12_context_check_2026-10-06.json) |
| 2026-10-06 | 인젝션 평가 (사전 등록) | 사례·채점기·판정 기준을 모델 실행 전에 GitHub에 push한 뒤 기준선 → 완화책 설계(dev만) → 봉인한 test 1회 | test 공격 성공 1/18 → 0/18로 등록 기준은 충족했지만 1건 차이이고 새 실패가 생겨 기본값에 미적용. 등록한 탐지기의 한계도 함께 보고 | [report](../eval/agent_injection_2026-10-06/REPORT.md) |
| 2026-10-06 | 공개 준비 | 로컬 절대경로 가림, 공개 안전성 검사, git 기록 시작 | 13개 파일에서 경로 133곳을 가림. 경로만 바뀌었는지 역변환으로 확인 | [redaction manifest](../eval/redaction_manifest_2026-10-06.json) |
