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

2. `.env.example` 을 `.env` 로 복사하고 키를 채웁니다.

   | 변수 | 쓰임 |
   | --- | --- |
   | `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 로그 조회. 없으면 수집 기능이 비활성됩니다 |
   | `LANGFUSE_HOST` | 리전에 맞는 주소 (EU/US/JP/셀프호스트) |
   | `OPENAI_API_KEY` | 채점·개선책·테스트 데이터 생성. 없으면 조회만 가능합니다 |
   | `OPENAI_JUDGE_MODEL` | judge 모델 (기본 `gpt-4o`) |

   키는 `.env` 에만 두고 커밋하지 않습니다.

## 실행

`scripts/run-app.cmd` 를 **더블클릭**하면 앱이 뜨고 브라우저가 열립니다.
바탕화면에 바로 가기를 만들어 두면 클릭 한 번으로 실행됩니다. 창을 닫으면 종료됩니다.

터미널에서 직접 띄우려면:

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv run streamlit run app/main.py
```

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

- **처음 실행** — LangFuse 에 쌓인 로그를 처음부터 끝까지 전부 받아 저장합니다.
- **그 다음부터** — 마지막으로 훑은 시각 이후에 새로 생긴 것만 받아 기존 목록에 합칩니다.
- 한 번 저장한 로그는 지우지 않습니다. 중간에 끊겨도 다음 실행이 그 지점부터 이어받습니다.

자세한 계약은 [수집 저장소 문서](.agents/knowledge/domain/collection-store.md) 를 참고합니다.

## 저장 구조

모든 산출물은 `data/` 아래 json 으로 남습니다(`.gitignore` 대상, 로컬 전용).

```
data/
├── collection.json         # 누적 수집된 트레이스 요약 (최신순, id 유일)
├── collection.state.json   # 증분 동기화 커서
├── tasks/<taskId>/         # trace.json · prompts.json
├── evaluations/<taskId>.json
├── prompts/<이름>/v<n>.json  # 편집 가능한 프롬프트 버전
├── improvements/
└── testdata/
```

경로 규칙의 정본은 [app/storage/paths.py](app/storage/paths.py) 입니다. 다른 코드는 경로 문자열을
직접 조합하지 않습니다.

## 개발

```powershell
.venv\Scripts\python.exe -m unittest tests.test_collection_sync tests.test_v4_rubric tests.test_evaluation_results_ui
```

- 작업 지침: [AGENT.md](AGENT.md)
- 계약·용어 문서: [.agents/knowledge/](.agents/knowledge/README.md)
- 계획·작업 로그: [.agents/plan/](.agents/plan/README.md) · [.agents/worklog/](.agents/worklog/README.md)
