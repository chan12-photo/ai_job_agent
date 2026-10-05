> 이 문서는 2026-10-06까지 저장소 첫 화면(README)이었던 상세 사용·운영 설명입니다. 내용은 그대로 두고 상대 링크만 새 위치에 맞게 고쳤습니다. 프로젝트 소개는 [README](../README.ko.md)를 보세요.

# AI Job Agent — Phase 4 M1 구현

공고 원문·지원 상태 관리(M0), 검토한 TXT/MD 문서의 버전·검색(Phase 2), 로컬 모델의 JD 추출 초안(Phase 3), 요구사항별 근거 연결과 분석 보존(M1)을 제공합니다. CLI와 Mac의 로컬 웹 화면이 같은 SQLite DB와 기존 처리 함수를 사용합니다. 유료 API·외부 DB·원격 모델로 자동 전환하지 않습니다. 설계 기준은 [Phase 0 v0.2](../AI_Job_Agent_Phase0_2026-09-29.md)입니다.

## Mac 로컬 웹 화면

프로젝트 폴더에서 Python 3.10 이상으로 실행합니다. 화면을 여는 데 추가 패키지나 유료 서비스는 필요하지 않습니다.

```sh
python3 -m job_agent.web
```

브라우저에서 `http://127.0.0.1:8765/`을 열고 공고 원문을 등록하세요. 목록에서 공고를 선택하면 원문·마감 정보, 지원 상태와 메모, 저장된 분석을 볼 수 있습니다. 지원 기록은 저장 버튼을 누를 때만 바뀝니다. 서버는 `127.0.0.1`에서만 접속을 받으며, 중단하려면 실행한 터미널에서 `Ctrl+C`를 누르세요. 기본 DB는 아래 CLI와 같은 `~/Library/Application Support/AIJobAgent/jobs.sqlite3`입니다. 별도 DB로 시험할 때는 `python3 -m job_agent.web --db /path/to/test.sqlite3 --port 8766`을 사용합니다.

새 분석은 공고 상세의 **분석 실행** 버튼을 눌렀을 때만 시작됩니다. 분석 전에는 검토한 경력 문서를 아래 `doc-add --verified` 명령으로 같은 DB에 등록해야 근거를 검색할 수 있습니다. 분석할 때는 Ollama가 별도 터미널에서 실행 중이어야 하며, 화면의 모델명은 **이미 설치된 로컬 모델**이어야 합니다. 진행 중에는 화면이 2초마다 갱신되고 같은 공고의 중복 요청은 하나의 실행으로 처리됩니다. 다른 공고의 분석은 진행 중인 실행이 끝난 뒤 시작할 수 있습니다. Ollama가 꺼져 있으면 해당 분석이 실패 기록으로 저장될 수 있지만 공고 관리와 기존 분석 조회는 계속 사용할 수 있습니다.

저장된 분석에서 추출 정보, 요구별 판정, 선택 근거 원문과 문서 출처, 선택하지 않은 검색 후보, 단계 오류를 확인하세요. **AI 판정은 검토 전 초안**이며 `partial`은 전체 지원 요건 충족을 뜻하지 않습니다. 사람이 남기는 분석 검토 상태와 지원 상태·메모는 각각 독립된 기록입니다. 분석 실행만으로 지원 상태는 바뀌지 않습니다. 화면은 자유 채팅이나 자율 도구 실행을 제공하지 않습니다.

현재 분석 진행 표시와 중복 실행 방지는 실행 중인 웹 서버 안에서만 유지됩니다. 분석 중 서버를 종료하면 그 실행의 완료 기록이 남지 않을 수 있으므로 완료 표시를 보고 종료하세요. 저장이 끝난 분석은 SQLite에 남아 재실행 후에도 조회할 수 있습니다.

### 이미지 공고 입력 · macOS Vision OCR

이미지 입력 화면에서 **⌘V 붙여넣기**, 이미지 파일 **끌어놓기**, **공고 이미지 선택**을 사용할 수 있습니다. Mac에서 **Control+Shift+Command+4**로 영역을 캡처하면 클립보드에 저장되므로 이 화면에서 Command+V로 붙여넣으세요. 일반 Shift+Command+4로 파일을 만들었다면 그 파일을 선택하거나 끌어 놓으면 됩니다. 여러 번 추가한 이미지는 선택 목록에 모이며 개별 제거가 가능합니다. **이미지 올리기**를 눌러야 로컬 서버의 원본 확인 화면으로 전달되고, OCR은 다음 화면에서 별도로 실행합니다.

첫 화면의 **공고 이미지로 등록**에서 PNG·JPG·JPEG를 1~5장 선택합니다. 한 장은 8 MiB 이하, 합계는 30 MiB 이하이고, 한 변 8000픽셀·전체 2400만 픽셀 이하입니다. 확장자와 실제 이미지 형식·해상도를 확인합니다. 이미지 순서를 바꾸거나 개별 이미지를 제거한 뒤 **OCR 실행**을 누르세요. 원본과 이미지별 추출문을 함께 보며 글자를 고치고, 필요하면 **이미지별 수정문으로 다시 구성**한 후 최종 공고 원문을 편집합니다. 여러 직무가 한 이미지에 있으면 해당 직무의 문구만 남기세요. 원본과 비교했다는 확인란을 선택하고 **확인한 원문 등록**을 눌러야 기존 공고 등록 함수가 호출됩니다. AI 분석은 등록 후 공고 상세에서 별도로 실행합니다.

OCR은 이 Mac에 이미 들어 있는 [Apple Vision의 텍스트 인식](https://developer.apple.com/documentation/vision/recognizing-text-in-images)을 Swift로 호출합니다. 한국어·영어 지원 여부를 실제 실행 시 확인합니다. Tesseract나 이미지 모델, 유료 API를 설치하거나 다운로드하지 않습니다. Ollama가 꺼져 있어도 이미지 업로드·OCR·수정·등록이 됩니다. Vision이 글자를 못 찾거나 오류가 나면 원본을 보며 최종 원문에 직접 입력하거나 첫 화면의 수동 등록을 사용하세요. OCR 신뢰도 점수는 표시하지 않습니다.

마감일, 연수, 필수·우대, 부정 표현, 2열/여러 직무의 읽기 순서가 틀릴 수 있습니다. 특히 추출된 마감 표현만 보고 날짜나 시각을 추정하지 마세요. 등록한 원본 이미지는 공고 상세에서 다시 볼 수 있습니다. 기존과 같은 원문이면 기존 공고에 이미지를 연결하며 지원 상태와 기존 분석은 그대로 둡니다.

업로드 후 아직 등록하지 않은 원본과 수정문은 DB 옆의 `jobs.sqlite3.assets/drafts`에 최대 24시간 보관하며 다음 이미지 화면 접속·업로드 때 만료 초안을 정리합니다. 등록 후 원본은 `jobs.sqlite3.assets/images`에 공고와 연결해 보관하고 초안은 제거합니다. 등록된 이미지의 자동 삭제 기능은 없습니다. `--db`로 다른 DB를 지정하면 그 DB 이름의 `.assets` 폴더를 사용합니다. DB를 백업하거나 옮길 때 원본 이미지도 필요하면 해당 자산 폴더를 함께 복사하세요. 저장소 안에 DB를 지정한 경우에도 `*.assets/`는 Git에서 제외됩니다.

이미지 첫 화면에서 보관 중인 초안을 다시 열 수 있습니다. **수정 내용 임시 저장**을 눌러야 편집 내용이 보존됩니다. 보관 기간은 최초 업로드부터 24시간이며 임시 저장으로 연장되지 않습니다. 공고와 이미지 연결은 함께 저장하고 일반 저장 오류 시 함께 롤백합니다. OCR이 끝나기 전에 서버를 종료했다면 초안을 열어 다시 실행하세요. 실제 가상 이미지에서 발견한 오독과 검증 범위는 [이미지 입력 검증 기록](../eval/ocr_ui_2026-10-01.md)에 남겼습니다.

## 실행

프로젝트 폴더에서 Python 3.10 이상으로 실행합니다. 수동 관리와 문서 검색에는 추가 패키지 설치가 필요 없습니다.

```sh
python3 -m job_agent add --file /path/to/job.txt --deadline-raw '10월 중'
python3 -m job_agent list
python3 -m job_agent show 1
python3 -m job_agent update 1 --revision 0 --status preparing --notes '가상 예시 메모'
python3 -m job_agent backup /path/to/backup.sqlite3
```

`--deadline-date 2026-10-31`은 연·월·일을 사용자가 확인했을 때만 지정합니다. 원문에 시각이 없으면 시각은 계속 미확인입니다. `--rolling`은 채용 시 마감입니다. 날짜 미확인 공고는 확인된 날짜 뒤에 나옵니다.

기본 DB는 `~/Library/Application Support/AIJobAgent/jobs.sqlite3`에 생성됩니다. 실험용 데이터는 `--db /path/to/test.sqlite3`를 **명령 앞에** 두어 분리할 수 있습니다. 저장소에는 실제 이력서·공고·DB를 넣지 마세요.
같은 폴더의 `events.jsonl`에는 명령·성공/실패·공고 ID·오류 종류만 기록하며, 원문과 메모는 기록하지 않습니다.

동일한 원문을 다시 `add`하면 기존 공고를 반환하고 지원 기록은 바꾸지 않습니다. 동일 원문의 다른 모집 회차라면 `--new-round`를 명시하세요. 수정 시 `show`에 나온 revision을 넣어야 하며, 다른 수정이 먼저 반영되었다면 조회 후 다시 수정해야 합니다. 메모만 바꾸거나 `--notes ''`로 지울 수도 있습니다.

백업 명령은 SQLite backup API로 일관된 스냅샷을 만듭니다. 복원하려면 프로그램을 종료한 후 기존 DB를 별도 보관하고 백업 파일을 DB 경로에 복사하세요. 먼저 `python3 -m job_agent --db /path/to/backup.sqlite3 list`로 백업을 조회할 수 있습니다.

## 검토한 문서 등록과 검색

```sh
python3 -m job_agent doc-add --file /path/to/reviewed.md --title '검토한 경력 문서' --verified
python3 -m job_agent doc-list
python3 -m job_agent search 'Python SQL'
python3 -m job_agent evidence 1

# 문서 #1의 수정본을 별도 버전으로 저장하고 검색 대상을 바꿉니다.
python3 -m job_agent doc-add --file /path/to/revised.md --replace 1 --verified
python3 -m job_agent doc-versions 1
python3 -m job_agent search 'Python' --version 1
python3 -m job_agent doc-activate 1
```

`doc-add`는 사용자가 직접 지정하고 검토했다고 표시한 UTF-8 `.txt`/`.md` 파일 한 개만 읽습니다. 최대 크기는 2 MiB입니다. 파일 경로나 파일명만 같다는 이유로 내용을 덮어쓰지 않습니다. `--replace`는 기존 문서 ID에 새 버전을 추가하고 그 버전을 활성화합니다. 내용이 현재 활성 버전과 완전히 같으면 재등록하지 않습니다. `doc-activate`는 이전 버전을 다시 활성화합니다.

기본 검색은 **활성 버전**만 대상으로 합니다. `--version`을 주면 특정 이전 버전을 명시적으로 검색할 수 있습니다. 결과의 `[시작:끝]`은 저장된 원문 문자열의 0부터 시작하는 문자 위치이며 끝은 포함하지 않습니다. `evidence`로 저장된 구간을 다시 확인할 수 있습니다. 검색은 관련 문단 후보를 정렬할 뿐, 실제 경험이나 자격 충족 여부를 판단하지 않습니다. 부정 표현이 든 문단도 후보로 나올 수 있습니다.

한국어는 부분 문자열, 영문 기술명은 단어 경계로 찾습니다. 수동 한영 동의어는 이번 검색에서만 `--alias '파이썬=Python'`처럼 지정합니다. 검색어가 문서 전체의 표현과 다르면 후보를 놓칠 수 있습니다.

## 로컬 JD 추출 초안

AI를 사용할 때만 Ollama와 로컬 모델이 필요합니다. 이 프로젝트가 사용한 설치·시험 명령은 다음과 같습니다. 첫 모델 다운로드에는 인터넷과 약 1.4GB의 저장 공간이 필요합니다.

```sh
brew install ollama
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

위 서버 명령은 별도 터미널에서 실행해 두고, 다른 터미널에서 모델을 준비하고 공고를 분석합니다.

```sh
ollama pull qwen3:1.7b
python3 -m job_agent model-list
python3 -m job_agent analyze 1 --model qwen3:1.7b
```

`analyze`는 저장된 공고를 로컬 `127.0.0.1:11434`의 **이미 설치된 모델**에 보내고 검토 전 초안을 화면에 표시합니다. 분석 결과를 DB에 저장하거나 지원 상태를 수정하지 않습니다. 원문이 3,000자를 넘으면 잘라서 보내지 않고 오류로 중단합니다. 모델 출력의 JSON 구조와 모든 인용 구절을 원문과 대조하며, 잘못된 출력은 한 번만 재시도합니다. 현재 검사는 공고 앞의 자료 표식을 회사명으로 쓰거나 `주요 업무`처럼 명시된 업무 구절을 누락한 출력을 거부합니다. 복구에 실패하면 분석 전체가 실패로 남습니다. 인용이 맞더라도 다른 회사·직무 분류, 요구사항 누락, 부정 표현 해석은 틀릴 수 있습니다. 마감일은 원문 표현만 보여주며 연도·시각을 보충하지 않습니다.
같은 인용 구절이 원문에 여러 번 있으면 표시 위치는 첫 등장 위치입니다.

Ollama가 꺼져 있거나 모델이 없으면 `analyze`만 실패하고 기존 명령은 계속 사용할 수 있습니다. 시험에 사용한 실제 모델·설정·가상 공고 결과는 [평가 기록](../eval/README.md)에 있습니다. 로컬 서버 설정은 [Ollama 공식 FAQ](https://docs.ollama.com/faq), 구조화 출력 형식은 [Ollama API 문서](https://github.com/ollama/ollama/blob/main/docs/api.md)를 참고했습니다.

## 요구사항별 근거 연결 M1

`run`은 저장된 공고와 현재 활성 문서 버전을 읽고 JD 추출 → 요구별 검색 → 로컬 모델의 연결 제안 → 허용 ID 및 원문 구간 확인 → SQLite 저장 순서로 실행합니다. 지원 상태와 메모는 바꾸지 않습니다. 모델을 명시해야 하며 서버가 꺼져 있어도 저장된 분석은 조회할 수 있습니다.

```sh
python3 -m job_agent run 1 --model qwen3:4b-instruct-2507-q4_K_M
python3 -m job_agent analysis-list --job 1
python3 -m job_agent analysis-show 1
python3 -m job_agent analysis-show 1 --json
python3 -m job_agent analysis-review 1 --revision 0 --status reviewed
```

검색 표현이 다르면 `run`에 `--alias '파이썬=Python'`을 추가할 수 있습니다. `--top-k 1`부터 `5`까지 후보 수를 조정할 수 있습니다. 분석에는 입력 공고 스냅샷, 사용한 문서 버전, 후보 ID와 순서, 모델 digest와 옵션, 프롬프트 내용 및 출력 상태가 보존됩니다. 문서 버전이 바뀌어도 이전 분석은 덮어쓰지 않고 조회 시 이전 버전 경고를 표시합니다. `analysis-review`의 revision은 분석 검토 기록의 번호이며 지원 상태의 revision과 별개입니다.

`analysis-show`는 사용한 모델·JD/매칭 버전, 모델이 선택한 근거, **선택하지 않은 검색 후보**를 구분해 보여줍니다. 선택하지 않은 후보도 관련 문장일 수 있으므로 충돌이나 누락을 확인할 때 함께 읽으세요. 검색 후보라는 이유만으로 자격 충족 근거가 되지는 않습니다. 이전 버전의 저장 결과도 후보 ID를 통해 원문을 다시 보여주며, 자유 서술이 포함될 수 있는 옛 매칭 결과에는 경고를 표시합니다.

`review_ready`도 정확성 인증이 아니라 모든 요구에 대해 형식상 결과가 만들어졌다는 뜻입니다. `partial`은 일부 요구의 모델·검증 오류, `no_evidence`는 검색 후보 전체 미발견, `failed`는 추출 실패입니다. 모델 요청이나 검색 중 전체 실행 시간이 초과되면 `timed_out`, 추출·검색·매칭 도중 사용자가 중단하면 `cancelled`로 저장합니다. 초기 DB 연결·조회 또는 최종 저장 도중 중단하면 CLI는 종료 코드 130을 반환하지만 분석 기록이 남지 않을 수 있습니다. `run`의 종료 코드는 `review_ready`·`no_evidence` 0, `partial` 2, `failed`·`timed_out` 1, `cancelled` 130입니다. 저장된 실패 결과는 `analysis-list`와 `analysis-show`에서 확인할 수 있습니다.

근거 ID·구간 검사는 사실 관계의 의미를 증명하지 못합니다. 초기 시험에서 모델이 미기재를 경험 부재로 단정했기 때문에 현재 `match-v5`는 모델의 자유 서술을 받지 않고 판정과 근거 ID만 받습니다. 화면의 설명은 고정 문구이며, **미확인 요구 범위는 세부 누락 조건을 추정하지 않고 요구 원문 전체**를 표시합니다. 이전 버전으로 저장된 분석에는 당시 모델 문장이 남아 있으므로 직접 검토해야 합니다. M1은 작업당 모델 호출 최대 8회, 출력 복구 총 1회, 전체 300초 제한을 적용합니다. 긴 입력을 조용히 자르지 않습니다. 품질 합격 여부는 [평가 기록](../eval/README.md)에 따로 적었습니다.

이전 M1 DB를 열면 새 종료 상태를 저장할 수 있도록 분석 테이블 구조를 한 번 갱신합니다. 기존 분석·검토 기록은 보존합니다. 중요한 실제 데이터가 있다면 첫 실행 전에 프로그램을 종료하고 원본 SQLite 파일을 별도 위치에 복사해 두세요. 앱의 `backup` 명령도 DB를 열면서 이 구조 갱신을 먼저 수행합니다.

가상 자료 20건의 전체 흐름을 두 번 실행한 결과 연결 판정은 각각 16/20이었습니다. 기간 부족, 여러 조건 중 일부만 충족, 상충 기록, 여러 문서의 근거 결합에서 오류가 남았습니다. 검색된 근거를 읽고 지원 자격을 직접 결정해야 합니다. 이 결과만으로 M1을 품질 합격으로 표시하지 않습니다.

추가 지시문 실험은 기존 20건의 매칭 단독 정확도를 18/20에서 17/20으로 낮춰 제품에 적용하지 않았습니다. 별도 가상 8건에서는 5/8에서 7/8로 올랐지만 일부 팀 성과·기간 사례에 새 오답이 생겼습니다. 실험 자료와 재현 방법은 [평가 기록](../eval/README.md)에 있습니다.

## 제한된 읽기 전용 로컬 CLI Agent

`agent-read`는 사용자가 명시한 workspace 안에서만 동작하는 단일 질문용 읽기 Agent입니다. Ollama native `tools`와 `message.tool_calls`를 사용하며, 모델에는 `list_files`, `read_file`, `search_text` 세 도구만 노출합니다. 파일 수정·삭제·셸·Git·인터넷 검색 도구는 없습니다. workspace는 반드시 `--workspace`로 지정해야 하며 홈 폴더나 현재 프로젝트 전체를 자동으로 탐색하지 않습니다.

```sh
python3 -m job_agent agent-read \
  --workspace eval/agent_phase1_demo_workspace_2026-10-05 \
  --question 'src/report.py 파일에서 CODE_RED를 찾아줘.' \
  --model qwen3:4b-instruct-2507-q4_K_M
```

기본 로그는 `~/Library/Application Support/AIJobAgent/agent_runs`에 JSON으로 저장됩니다. 로그에는 사용자 질문, 모델 요청 payload, 원시 응답, 도구 인자, 도구 결과, 읽은 원문 일부가 포함됩니다. 저장소 안에 로그 폴더를 지정할 경우 `.gitignore`에 포함된 `agent_runs/` 또는 `eval/agent_*_logs_*/` 같은 제외 경로를 사용하세요. 로그에는 workspace 절대경로가 들어가므로 저장소에 올리지 마세요. 모델이 만든 도구 인자와 서버가 검증한 인자는 따로 기록합니다. 한 assistant 응답에 여러 독립 읽기 tool call이 들어오면 묶음 전체를 먼저 검증하고, 모두 통과할 때만 반환 순서대로 실행합니다. 예산 초과·금지 경로·중복 호출이 하나라도 있으면 그 묶음은 실행하지 않습니다.

읽기 도구는 workspace 상대 경로만 허용합니다. 절대경로, `..`, symlink, `.env`, SQLite/DB, 키 파일, GGUF, 로그, `*.assets/`, `.git` 등은 거부하거나 검색에서 제외합니다. 검색은 파일 수·파일 크기·결과 수 제한을 기록하며, 건너뛴 파일이 있으면 `search_complete=false`로 표시합니다. 파일 내용에 지시문이 있어도 데이터로만 처리하며 실제 접근 권한은 서버 검증이 결정합니다.

종료 상태는 `completed`, `unverified_final`, `policy_or_tool_error`, `protocol_error`, `repeated_action`, `budget_exhausted`, `context_budget_exceeded`, `incomplete_model_response`, `timed_out`, `cancelled`, `ollama_error`로 구분됩니다. 로그 저장 결과는 실행 상태와 별도로 `persistence_status`(`saved`/`failed`)에 기록하며, 저장에 실패하면 종료 코드 1과 stderr 경고를 내고 `log_path`는 비워 둡니다(`log_write_failed`는 Phase 1.2부터 실행 상태로 쓰지 않습니다). `completed`는 도구 근거가 있는 최종 답변에 도달했다는 뜻이며 답변의 모든 문장이 의미적으로 검증됐다는 뜻은 아닙니다. 근거 ID와 경로는 사용자가 원문을 다시 확인하기 위한 표시입니다.

Phase 1 시연 fixture는 [agent_phase1_cli_demo_cases_2026-10-05.json](../eval/agent_phase1_cli_demo_cases_2026-10-05.json)과 [agent_phase1_demo_workspace_2026-10-05](../eval/agent_phase1_demo_workspace_2026-10-05)에 있습니다. 재현 명령은 다음과 같습니다.

```sh
python3 -m eval.run_agent_phase1_cli_demo \
  --output /tmp/agent_phase1_cli_demo_results.json \
  --report /tmp/agent_phase1_cli_demo_report.md \
  --log-dir /tmp/agent_phase1_cli_logs
```

2026-10-05 실제 실행에서는 처음 Ollama가 꺼져 있어 6건 모두 `ollama_error`로 끝났고 모델 호출은 0회였습니다. 이후 `OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve`로 이 작업에서만 서버를 시작해 다시 실행했습니다. 재실행 결과는 5/6 성공, 모델 생성 요청 12회, prompt/output token 13768/422, Agent 내부 소요 8064.705ms였습니다. 두 파일을 동시에 읽는 요청은 모델이 첫 응답에서 두 tool call을 한꺼번에 반환했고, 당시 CLI가 응답 하나당 tool call 하나만 지원해 `protocol_error`로 종료했습니다. 이 실패 기록은 보존합니다.

2026-10-06 Phase 1.1에서는 같은 fixture를 새 CLI로 다시 실행했습니다. 결과는 6/6 성공, 모델 생성 요청 13회, prompt/output token 16080/429, Agent 내부 소요 8202.224ms였습니다. 두 파일 읽기 사례에서 첫 모델 턴은 `read_file(docs/alpha.md)`와 `read_file(docs/beta.md)`를 같은 응답에 반환했고, CLI는 두 결과를 순서대로 실행해 후속 모델 턴에 `system,user,assistant,tool,tool` 순서로 전달했습니다. 새 결과는 [Phase 1.1 보고서](../eval/agent_phase1_1_report_2026-10-06.md)에 있습니다. 이 검증은 기존 6개 가상 fixture에 대한 확인이며 파일 수정 Agent나 실제 프로젝트 전체 신뢰성을 뜻하지 않습니다.

2026-10-06 Phase 1.2에서는 접근 정책과 기록 정확성을 보강했습니다. `.ENV`, `.GIT`, `*.SQLITE3`, `*.ASSETS` 같은 대소문자 변형과 `.ssh/id_rsa`, `.aws/credentials`, `.netrc`, `.ollama/id_ed25519` 같은 대표 민감 경로를 차단합니다. `/`와 사용자 홈 자체는 workspace로 거부합니다. 검색이 결과 수·방문 수·시간 제한 때문에 멈추면 `search_complete=false`로 표시합니다. 로그는 한 번만 저장하며 실행 상태와 로그 저장 상태를 구분합니다. `done=false` 또는 `done_reason=length` 모델 응답은 `completed`로 처리하지 않습니다. 자세한 내용은 [Phase 1.2 보고서](../eval/agent_phase1_2_report_2026-10-06.md)와 [HANDOFF](../HANDOFF.md)에 있습니다.

2026-10-06 후속 보강에서는 컨텍스트 처리 방식을 실제 Ollama 0.34.4에서 확인하고 바로잡았습니다. 기본 설정의 Ollama는 대화가 `num_ctx`(4096 tokens)를 넘으면 오래된 메시지를 **조용히 버리고** 정상 응답처럼 답했습니다(합성 시험에서 질문이 담긴 메시지가 빠져 모델이 `UNKNOWN`이라고 답함). 이제 `/api/chat` 요청에 `truncate=false`, `shift=false`를 보내 서버가 초과 요청을 거부하게 하고, 그 거부(HTTP 400 `exceed_context_size_error`)를 `context_budget_exceeded`로 기록합니다. 실제 prompt token 수와 `num_ctx`, 이미 읽은 근거는 로그와 CLI 출력에 남습니다. `shift=false`의 효과는 이번 시험에서 확인하지 못했습니다. `MAX_MODEL_PAYLOAD_BYTES`(120,000 bytes)는 요청 크기 상한일 뿐 token 예산이 아니며, 실제 token 한도는 Ollama가 판정합니다. 그래서 현재 설정에서는 약 10KB 숫자 파일처럼 token이 많은 파일을 읽은 뒤의 모델 호출이 `context_budget_exceeded`로 끝날 수 있고, 큰 파일 페이지 읽기는 아직 없습니다. 같은 보강에서 권한 오류 같은 파일시스템 오류 메시지에서 절대경로를 제거했고, 읽을 수 없는 디렉터리 목록은 `protocol_error`가 아닌 도구 오류로 처리합니다. 배치 실행 중 Ctrl+C가 나면 진행 중이던 호출과 실행하지 못한 호출을 구분해 기록합니다. 자세한 내용은 [후속 보강 보고서](../eval/agent_phase12_followup_report_2026-10-06.md)에 있습니다.

## 검증

```sh
python3 -m unittest discover -s tests -v
```

가상 검색·JD·M1 사례와 기준선은 [eval/README.md](../eval/README.md)에 있습니다. Agent와 자동 지원 상태 변경은 없습니다. 날짜와 지원일은 추정하지 않습니다. SQLite 파일은 자체 암호화되지 않으므로 Mac의 접근 권한과 백업 위치를 관리해야 합니다.
