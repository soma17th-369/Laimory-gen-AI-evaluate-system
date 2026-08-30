# Laimory-gen-AI-evaluate-system

Laimory 에서 쓰이는 생성형 AI 의 품질을 측정하고 개선하기 위한 **로컬 GUI 도구**입니다.
대상 API 서버가 **LangFuse** 에 남긴 실행 로그를 읽어 동작 과정을 분석하고, 점수를 매기고,
문제점을 찾아 프롬프트 개선 방향과 테스트 데이터를 만듭니다.

대상 생성형 AI 는 이 저장소 밖에 있습니다. 여기서 다루는 입력은 **LangFuse 로그**입니다.

## 준비

1. 의존성 설치 (Windows 는 로컬 캐시를 씁니다)

   ```powershell
   $env:UV_CACHE_DIR=".uv-cache"
   uv sync
   ```

2. Codex CLI를 확인하고 ChatGPT 계정으로 로그인합니다. ChatGPT 데스크톱 앱의 로그인 상태와
   CLI 인증 상태가 같다고 가정하지 않습니다.

   ```powershell
   codex --version
   codex login
   codex login status
   ```

3. `.env.example` 을 `.env` 로 복사하고 필요한 값을 채웁니다.

   | 변수 | 쓰임 |
   | --- | --- |
   | `LANGFUSE_DEV_PUBLIC_KEY` / `LANGFUSE_DEV_SECRET_KEY` | 개발(dev) 프로젝트 로그 조회 |
   | `LANGFUSE_PROD_PUBLIC_KEY` / `LANGFUSE_PROD_SECRET_KEY` | 운영(prod) 프로젝트 로그 조회 |
   | `LANGFUSE_HOST` | 리전에 맞는 주소 (EU/US/JP/셀프호스트). 두 프로젝트 공통 |
   | `LANGFUSE_DEV_HOST` / `LANGFUSE_PROD_HOST` | 인스턴스가 서로 다를 때만. 비우면 `LANGFUSE_HOST` |
   | `LLM_PROVIDER` | 모든 LLM 기능의 실행 방식. 기본 `codex`, 호환용 `openai-api` |
   | `CODEX_MODEL` | Codex 모델. 비우면 Codex CLI 기본 모델 |
   | `CODEX_TIMEOUT_SECONDS` | Codex 실행 한 번의 제한 시간(기본 600초) |
   | `OPENAI_API_KEY` | deprecated OpenAI API provider를 선택할 때만 필요 |
   | `OPENAI_JUDGE_MODEL` | deprecated OpenAI API provider가 쓸 모델(기본 `gpt-4o`) |

   키가 있는 프로젝트만 수집합니다. 접두사 없는 예전 이름
   (`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`)은 **dev 값으로 계속 읽으므로**, 쓰던 `.env` 를
   그대로 두고 `LANGFUSE_PROD_*` 두 줄만 더하면 됩니다.

   키는 `.env` 에만 두고 커밋하지 않습니다. Codex 실패 시 OpenAI API로 자동 fallback하지
   않으며 provider는 `LLM_PROVIDER`로만 명시적으로 바꿉니다.

### LLM 실행 방식

Task 채점, 프롬프트 개선 제안, 개선책 본문, 테스트 데이터 생성의 기본 경로는 모두
`CodexProvider → codex exec`입니다. 각 호출은 이전 대화를 이어받지 않는 `--ephemeral` 실행이고,
읽기 전용의 빈 임시 디렉터리에서 동작합니다. 지시와 입력은 stdin으로 전달합니다. 구조화 결과는
기능별 Pydantic JSON Schema를 `--output-schema`로 강제하고 저장 전에 같은 모델로 다시 검증합니다.

상위 기능에는 OpenAI 직접 호출이 없지만, 기존 API 구현은 deprecated provider로 남아 있습니다.
필요할 때만 `.env`에서 다음처럼 명시합니다.

```dotenv
LLM_PROVIDER=openai-api
OPENAI_API_KEY=...
OPENAI_JUDGE_MODEL=gpt-4o
```

## 실행

`scripts/run-app.cmd` 를 **더블클릭**하면 앱이 뜨고 브라우저가 열립니다.
바탕화면에 바로 가기를 만들어 두면 클릭 한 번으로 실행됩니다. 창을 닫으면 종료됩니다.

터미널에서 직접 띄우려면:

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv run streamlit run app/main.py
```

## 개발·운영 프로젝트 함께 보기

LangFuse 프로젝트가 개발·운영으로 나뉘어 있어도 **화면은 갈라지지 않습니다.** 키가 설정된
프로젝트를 모두 받아 **한 목록에 시간순으로** 늘어놓고, 어디서 온 로그인지는 `env` 열로만
구분합니다.

- 로그 수집 버튼 한 번이면 개발·운영을 차례로 받아 같은 목록에 합칩니다.
- 대시보드·Task 리뷰·채점 결과·개선 history 모두 합친 목록을 봅니다. 건수는 환경별로도 함께
  보여줍니다.
- 상세 조회(트레이스 상세·모델·토큰)는 **그 행이 온 프로젝트로** 보냅니다.
- 환경마다 따로 가는 것은 **동기화 진행 상태(커서) 하나**뿐이라, 한쪽을 다시 훑어도 다른 쪽
  진행이 밀리지 않습니다.

자세한 계약은 [LangFuse 환경 문서](.agents/knowledge/domain/langfuse-environments.md) 를 참고합니다.

## 페이지

| 페이지 | 하는 일 |
| --- | --- |
| 📊 대시보드 | 수집된 로그의 건수·비용·latency·이름별 분포 |
| 📥 LangFuse 로그 수집 | 로그를 로컬에 누적 저장. 다른 페이지는 여기서 쌓은 로그만 씁니다 |
| 🔍 Task 리뷰·채점 | taskId 단위로 처리 과정·프롬프트를 보고 judge 로 채점 |
| 📋 채점 결과 | 저장된 채점 결과와 20개 정량 Metric 비교 |
| 🛠 개선책 | 채점 결과에서 프롬프트 개선 방향 도출. 반영 여부·시기도 여기서 관리 |
| 📈 개선 history | 반영된 개선책을 시간 순으로 놓고 반영 전후의 점수·비용·토큰·모델 변화 비교 |
| 🧪 테스트 데이터 | 개선책 또는 실제 로그 input 으로 테스트 스위트 생성 |

## 로그 수집 방식

수집은 **교체가 아니라 누적**입니다.

- **처음 실행** — 키가 설정된 프로젝트마다 쌓인 로그를 처음부터 끝까지 전부 받아 저장합니다.
- **그 다음부터** — 마지막으로 훑은 시각 이후에 새로 생긴 것만 받아 기존 목록에 합칩니다.
- 한 번 저장한 로그는 지우지 않습니다. 중간에 끊겨도 다음 실행이 그 지점부터 이어받습니다.

자세한 계약은 [수집 저장소 문서](.agents/knowledge/domain/collection-store.md) 를 참고합니다.

## 저장 구조

모든 산출물은 `data/` 아래 json 으로 남습니다(`.gitignore` 대상, 로컬 전용).

```
data/
├── collection.json         # 누적 수집된 트레이스 요약 (개발·운영 합계, 최신순, id 유일)
├── collection.state.json   # 증분 동기화 커서 (환경별: {"dev": …, "prod": …})
├── generations.json        # traceId → 모델·토큰 롤업 캐시
├── tasks/<taskId>/         # trace.json · prompts.json
├── evaluations/<taskId>.json
├── prompts/<이름>/v<n>.json  # 편집 가능한 프롬프트 버전
├── improvements/
└── testdata/
```

환경으로 폴더를 나누지 않습니다. 어느 프로젝트에서 왔는지는 행·레코드의 `env` 값이 들고 있고,
트레이스 id 와 taskId 가 전역 유일이라 파일명이 부딪히지 않습니다.

경로 규칙의 정본은 [app/storage/paths.py](app/storage/paths.py) 입니다. 다른 코드는 경로 문자열을
직접 조합하지 않습니다.

## 개발

```powershell
.venv\Scripts\python.exe -m unittest tests.test_collection_sync tests.test_environments tests.test_v4_rubric tests.test_evaluation_results_ui tests.test_improvement_history
```

- 작업 지침: [AGENT.md](AGENT.md)
- 계약·용어 문서: [.agents/knowledge/](.agents/knowledge/README.md)
- 계획·작업 로그: [.agents/plan/](.agents/plan/README.md) · [.agents/worklog/](.agents/worklog/README.md)
