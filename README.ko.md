# Local Agent Lab — 근거를 보여 줘야 하는 로컬 모델 Agent

[English](README.md) · **한국어**

로컬 폴더에 대한 질문에 도구 세 개(`list_files`, `read_file`, `search_text`)와 로컬 Ollama 모델로 답하는 읽기 전용 Agent입니다. 세 가지 원칙을 지킵니다.
- 모든 도구 호출은 파일을 열기 전에 경로 정책으로 먼저 검사합니다.
- 모든 실행은 기록되고, 그 기록을 재생할 수 있습니다.
- Agent를 바꿀 때마다 고정된 평가로 측정합니다. 일부 평가는 사전 등록했습니다.

유료 API나 클라우드로 자동 전환하는 경로는 없습니다.

**현재 수준.** 지금 모델(`qwen3:4b-instruct`, 4bit)로는 단순한 단일 파일 질문 10개 중 약 7개를 완전히 답합니다. 인젝션 평가의 봉인된 test set 기준선에서 17/24, 사용성 평가에서 10/12였습니다. 그래서 아직 매일 쓰는 도구라기보다 **측정과 안전장치를 위한 실험 플랫폼**입니다. 무료 20B 모델 `gpt-oss:20b`로 처음 비교해 보니 기존 평가의 합계 점수는 같았지만 이유가 달랐습니다. 더 잘 읽고 답했고 파일에 심은 출력 지시도 무시했지만, 경로 정책상 허용된 관련 없는 파일을 읽으라는 지시는 따랐습니다. 경로 정책만으로는 막을 수 없는 빈틈입니다. → [모델 비교](eval/model_check_2026-10-06/REPORT.md)

## 평가에서 발견한 것

- **Ollama는 대화가 컨텍스트 창을 넘으면 오래된 메시지를 조용히 버립니다.** 기본 요청에서 4,772 token짜리 대화가 오류 없이 3,542 token으로 잘렸습니다. 질문이 담긴 메시지가 사라졌고, 모델은 `done_reason=stop`과 함께 `UNKNOWN`이라고 답했습니다. 이제 Agent는 `truncate=false`를 보냅니다. 그래서 초과가 일어나면 명시적인 `context_budget_exceeded`로 끝나고, 이미 읽은 근거는 보존됩니다. → [후속 보강 보고서](eval/agent_phase12_followup_report_2026-10-06.md)
- **모델이 실수해도 정책 계층은 버팁니다.** 합성 Python 프로젝트 12건 사용성 평가에서 `.ENV` 파일 요청과 workspace 밖을 가리키는 symlink 요청은 파일을 열기 전에 거부됐고, 심어 둔 marker는 한 번도 새지 않았습니다. 같은 평가의 전체 점수는 10/12였습니다. 실패 중 하나(모델이 파일 안에 숨긴 지시를 따른 사례)는 재생 가능한 데모로 남겼습니다. → [사용성 평가 보고서](eval/agent_phase12_usability_report_2026-10-06.md)
- **사전 등록한 프롬프트 인젝션 평가를 나온 그대로 보고했습니다.** 사례, 채점기, 판정 기준을 모델 실행 전에 GitHub에 올렸습니다. 모델은 파일에 심은 지시를 거의 따르지 않았고, 도구 탈취 시도는 한 번도 없었습니다(봉인한 test set에서 등록 기준 공격 성공 1/18). 도구 결과에 "신뢰할 수 없는 데이터" 표시를 붙이고 사용자 질문을 다시 상기시키는 완화책은 등록한 기준을 충족했습니다(0/18). 다만 차이가 1건뿐이고, 파일을 읽기 전에 답하는 새 실패를 일으켰을 가능성이 있어 기본값으로 쓰지 않습니다. 등록한 탐지기가 모델의 주된 지시 수행 방식을 놓친 점도 다시 채점하지 않고 그대로 보고했습니다. → [인젝션 평가 보고서](eval/agent_injection_2026-10-06/REPORT.md)

## 1분 체험 (모델 불필요)

데모는 실제 실행에서 기록한 모델 응답을 재생합니다. 정책 검사와 도구는 저장소에 포함된 합성 workspace에서 실제로 실행됩니다. 코드, 프롬프트, 도구, 파일 중 무엇이든 바뀌어 대화가 기록과 달라지면, 재생은 없는 응답을 지어내지 않고 `replay_mismatch`로 멈춥니다.

```bash
git clone https://github.com/chan12-photo/local-agent-lab.git && cd local-agent-lab
python3 scripts/run_demo.py
```

마지막 줄에 `6/6 recorded runs reproduced without calling a model.`이 나오면 성공입니다. 재생 하나를 CLI 전체 출력으로 보거나 전체 테스트를 실행할 수도 있습니다(Python 3.10 이상, 표준 라이브러리만 사용).

```bash
python3 -m local_agent --replay demo/replays/06_context_overflow_rejected.json --log-dir /tmp/agent-demo-logs
python3 -m unittest discover -s tests
```

Ollama와 모델이 설치되어 있으면 아무 폴더에나 실제로 질문할 수 있습니다. 자세한 내용은 [docs/USAGE.md](docs/USAGE.md)에 있습니다.

```bash
python3 -m local_agent --workspace path/to/project --question "재시도 한도는 어디에 설정되어 있어?"
```

## 동작 방식

구조도는 [영문 README](README.md#how-it-works)에 있습니다. 핵심 설계 결정은 다음과 같습니다(자세한 내용은 [ADR](eval/adr_readonly_workspace_agent_2026-10-06.md)).

- **`completed`는 실행 상태일 뿐 채점 결과가 아닙니다.** 실행 완료 여부, 근거 존재 여부, 그리고 평가에서는 답의 정확성을 각각 따로 기록합니다.
- **도구 묶음은 전부 실행하거나 전혀 실행하지 않습니다.** 한 모델 턴의 호출 중 하나라도 정책이나 예산을 어기면 그 턴의 호출은 하나도 실행하지 않습니다.
- **쓰기·삭제·셸·Git 도구는 아직 없습니다.** 평가에서 모델이 파일 내용에 심은 지시를 따를 수 있음을 확인했습니다. 부작용이 있는 도구는 이 문제를 측정하고 완화한 뒤에 추가합니다.
- **조용한 품질 저하보다 드러나는 실패를 택합니다.** 컨텍스트 초과, 생성 중단(`done_reason=length`), 불완전 검색, 로그 저장 실패는 성공처럼 보이지 않도록 각각 별도 상태로 기록합니다.

## 저장소 구성

| 경로 | 내용 |
|---|---|
| [`local_agent/`](local_agent) | Agent 본체: 정책과 도구, Ollama 연결, 실행 루프와 기록(`readonly_agent.py`), 재생 클라이언트, CLI |
| [`tests/`](tests) | 단위·회귀·재생 테스트. 네트워크 없이 합성 자료만 사용 |
| [`eval/`](eval) | 모든 평가의 fixture, 실행기, 원시 결과, 날짜별 보고서 ([목록](docs/EVALUATION.md)) |
| [`demo/`](demo) | 재생 fixture와 그 대상인 합성 workspace |
| [`docs/`](docs) | [평가 목록](docs/EVALUATION.md), [개발 타임라인](docs/TIMELINE.md), [사용법](docs/USAGE.md), [인수인계 메모](docs/HANDOFF.md) |
| [`scripts/`](scripts) | 데모 실행, 공개 안전성 검사, 경로 가림, 재생 fixture 생성 |

## 개발 방식

이 프로젝트는 제 지휘 아래 AI 코딩 도구(OpenAI Codex, Anthropic Claude)와 함께 개발했습니다. 제 역할은 네 가지였습니다. 범위와 제약을 정하고, 만들지 않을 것을 결정하고, 한 AI가 다른 AI의 코드와 증거를 검토하는 교차 감사를 운영하고, 모든 주장을 재현한 뒤에만 고치거나 보고하게 하는 것입니다. 커밋에는 `Co-Authored-By` 표시가 붙어 있습니다. git 기록은 2026-10-06부터 시작하며, 그 이전 작업은 날짜별 보고서로 재구성한 [docs/TIMELINE.md](docs/TIMELINE.md)에 있습니다.

이 프로젝트는 로컬 채용공고 분석 도구에서 출발했습니다. 그 도구는 지금 별도 저장소 [job-posting-analyzer](https://github.com/chan12-photo/job-posting-analyzer)에 있습니다.

## 한계

- 가장 큰 한계는 현재 4B 모델의 능력입니다. 도구를 잘못 고르는 경우가 있고(예: 문장 전체를 검색어로 넣었다가 "결과 없음"으로 끝냄), `num_ctx=4096`에서는 token이 많은 파일을 읽지 못합니다.
- 평가 집합은 작은 합성 자료(각 5~24건)입니다. 회귀를 잡는 용도이며 일반적인 정확도를 입증하지 않습니다.
- Agent는 여전히 파일이 요구하는 토큰을 가끔 답변에 덧붙입니다(인젝션 평가 보고서 참고). 기본값으로 켜 둔 완화책은 없습니다.
- 테스트와 데모는 macOS에서만 실행했습니다. Linux·Windows는 확인하지 않았습니다.

## 라이선스

[MIT](LICENSE)
