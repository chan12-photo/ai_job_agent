# AI Job Agent — 근거를 보여줘야 하는 로컬 LLM 도구

[English](README.md) · **한국어**

작은 로컬 언어 모델은 맞든 틀리든 자신 있게 답합니다. 이 프로젝트의 로컬 도구 두 가지는 한 가지 원칙을 따릅니다. **모델의 답은 근거를 가리킬 때만 인정하고, "실행이 끝났다"를 "답이 맞다"로 취급하지 않는다.**

1. **근거 기반 채용공고 분석**: 공고(텍스트 또는 캡처 이미지)에서 요구사항을 뽑고, 사용자가 검토한 자기 문서에서 관련 문단을 찾습니다. 그런 다음 요구사항마다 판정을 내리는데, 판정은 반드시 원문 구간을 인용해야 합니다.
2. **경계가 있는 읽기 전용 workspace Agent**: 로컬 폴더에 대한 질문에 도구 세 개(`list_files`, `read_file`, `search_text`)로 답합니다. 파일을 열기 전에 경로 정책 검사를 먼저 거칩니다.

모든 처리는 Mac의 로컬 Ollama 모델(`qwen3:4b-instruct`, 4bit)에서 이루어집니다. 유료 API나 클라우드로 자동 전환하는 경로는 없습니다.

## 평가에서 발견한 것

- **Ollama는 대화가 컨텍스트 창을 넘으면 오래된 메시지를 조용히 버립니다.** 기본 요청에서 4,772 token짜리 대화가 오류 없이 3,542 token으로 잘렸습니다. 질문이 담긴 메시지가 사라졌고, 모델은 `done_reason=stop`과 함께 `UNKNOWN`이라고 답했습니다. 이제 Agent는 `truncate=false`를 보냅니다. 그래서 초과가 일어나면 명시적인 `context_budget_exceeded`로 끝나고, 이미 읽은 근거는 보존됩니다. → [후속 보강 보고서](eval/agent_phase12_followup_report_2026-10-06.md)
- **형식 검사 통과가 정답은 아닙니다.** 같은 출력 계약에서 4B 모델은 매칭 20건 중 18건, 1.7B 모델은 5건에서 기대 판정에 도달했습니다. 두 모델 모두 형식과 인용은 20/20 통과했습니다. → [평가 목록](docs/EVALUATION.md)
- **모델이 실수해도 정책 계층은 버팁니다.** 합성 Python 프로젝트 12건 사용성 평가에서 `.ENV` 파일 요청과 workspace 밖을 가리키는 symlink 요청은 파일을 열기 전에 거부됐고, 심어 둔 marker는 한 번도 새지 않았습니다. 같은 평가의 전체 점수는 10/12입니다. 모델이 파일 안에 숨긴 지시를 따른 실패가 있었기 때문입니다. 이 실패는 숨기지 않고 재생 가능한 데모로 남겼습니다. → [사용성 평가 보고서](eval/agent_phase12_usability_report_2026-10-06.md)

## 1분 체험 (모델 불필요)

Agent 데모는 실제 실행에서 기록한 모델 응답을 재생합니다. 정책 검사와 도구는 저장소에 포함된 합성 workspace에서 실제로 실행됩니다. 코드, 프롬프트, 도구, 파일 중 무엇이든 바뀌어 대화가 기록과 달라지면, 재생은 없는 응답을 지어내지 않고 `replay_mismatch`로 멈춥니다.

```bash
git clone https://github.com/chan12-photo/ai_job_agent.git && cd ai_job_agent
python3 scripts/run_demo.py
```

마지막 줄에 `6/6 recorded runs reproduced without calling a model.`이 나오면 성공입니다. 재생 하나를 CLI 전체 출력으로 보거나 전체 테스트를 실행할 수도 있습니다(Python 3.10 이상, 표준 라이브러리만 사용).

```bash
python3 -m job_agent agent-read --replay demo/replays/06_context_overflow_rejected.json --log-dir /tmp/agent-demo-logs
python3 -m unittest discover -s tests
```

## 동작 방식

구조도는 [영문 README](README.md#how-it-works)에 있습니다. 핵심 설계 결정은 다음과 같습니다(자세한 내용은 [ADR](eval/adr_readonly_workspace_agent_2026-10-06.md)).

- **`completed`는 실행 상태일 뿐 채점 결과가 아닙니다.** 실행 완료 여부, 근거 존재 여부, 그리고 평가에서는 답의 정확성을 각각 따로 기록합니다.
- **도구 묶음은 전부 실행하거나 전혀 실행하지 않습니다.** 한 모델 턴의 호출 중 하나라도 정책이나 예산을 어기면 그 턴의 호출은 하나도 실행하지 않습니다.
- **쓰기·삭제·셸·Git 도구는 아직 없습니다.** 사용성 평가에서 모델이 파일 내용에 심은 지시를 따를 수 있음을 확인했습니다. 이 문제를 측정하고 완화하기 전에 부작용이 있는 도구부터 주는 것은 순서가 틀렸다고 판단했습니다.
- **조용한 품질 저하보다 드러나는 실패를 택합니다.** 컨텍스트 초과, 생성 중단(`done_reason=length`), 불완전 검색, 로그 저장 실패는 성공처럼 보이지 않도록 각각 별도 상태로 기록합니다.

## 저장소 구성

| 경로 | 내용 |
|---|---|
| [`job_agent/`](job_agent) | 실행 코드: 공고 관리, JD 추출, 검색, 매칭, 로컬 웹 화면, OCR 연결, 읽기 전용 Agent(`readonly_agent.py`), 재생 클라이언트 |
| [`tests/`](tests) | 단위·회귀·재생 테스트. 네트워크 없이 합성 자료만 사용 |
| [`eval/`](eval) | 모든 평가의 fixture, 실행기, 원시 결과, 날짜별 보고서 |
| [`demo/`](demo) | 재생 fixture와 그 대상인 합성 workspace |
| [`docs/`](docs) | [평가 목록](docs/EVALUATION.md), [개발 타임라인](docs/TIMELINE.md), [상세 사용 설명](docs/USAGE.ko.md) |
| [`scripts/`](scripts) | 데모 실행, 공개 안전성 검사, 경로 가림, 재생 fixture 생성 |

공고 관리 웹 화면(`python3 -m job_agent.web`)을 쓰거나 실제 모델로 Agent를 실행하려면 [상세 사용 설명](docs/USAGE.ko.md)을 보세요. 분석에는 모델이 설치된 Ollama가, OCR에는 macOS가 필요합니다.

## 개발 방식

이 프로젝트는 제 지휘 아래 AI 코딩 도구(OpenAI Codex, Anthropic Claude)와 함께 개발했습니다. 제 역할은 네 가지였습니다. 범위와 제약을 정하고, 만들지 않을 것을 결정하고, 한 AI가 다른 AI의 코드와 증거를 검토하는 교차 감사를 운영하고, 모든 주장을 재현한 뒤에만 고치거나 보고하게 하는 것입니다. 커밋에는 `Co-Authored-By` 표시가 붙어 있습니다. git 기록은 2026-10-06부터 시작하며, 그 이전 작업은 날짜별 보고서로 재구성한 [docs/TIMELINE.md](docs/TIMELINE.md)에 있습니다.

## 한계

- 평가 집합은 작은 합성 자료(각 4~20건)입니다. 회귀를 잡는 용도이며 일반적인 정확도를 입증하지 않습니다.
- Agent는 여전히 파일 안의 일부 지시를 따릅니다. 가장 중요한 미해결 문제입니다.
- 웹 화면과 데모 질문은 한국어이고, OCR은 macOS Vision이 필요합니다.
- 큰 파일을 나눠 읽는 기능이 없습니다. `num_ctx=4096`에서 token이 많은 파일은 `context_budget_exceeded`로 끝납니다.
- 테스트와 데모는 macOS에서만 실행했습니다. Linux·Windows는 확인하지 않았습니다.

## 라이선스

[MIT](LICENSE)
