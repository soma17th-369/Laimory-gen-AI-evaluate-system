# LangFuse 평가 GUI — 초기 로드맵과 부트스트랩

- 상태: 진행 (M0·M1 완료 — M1 라이브 검증 통과)
- 관련 이슈: (없음)

## 배경·목표

대상 API 서버가 **LangFuse** 에 남긴 생성형 AI 실행 로그를 로컬 GUI 에서 분석·채점하고,
리포트를 바탕으로 프롬프트 개선 방향과 테스트 데이터를 만든다. 전체 그림은
[시스템 개요](../knowledge/domain/overview.md) 참고.

이 계획의 목표는 (1) 실행 가능한 Streamlit + langfuse SDK 골격을 세우고, (2)
[시스템 개요](../knowledge/domain/overview.md) 의 5단계 파이프라인을 마일스톤으로 쪼개
어디까지 왔는지 추적할 수 있게 하는 것.

## 범위 / 범위 밖

- **범위**: 로컬 실행 Streamlit 앱, LangFuse 공식 Python SDK 로그 수집, 분석·점수·문제점,
  리포트, 프롬프트 개선 제안, 테스트 데이터 생성.
- **범위 밖**: 대상 API 서버 자체의 수정, LangFuse 서버 운영, 배포/호스팅(이 도구는 로컬 전용),
  대상 서버 DB·코드 직접 접근.

## 접근

- 스택: Python + `uv`, GUI 는 **Streamlit**(로컬 브라우저), 로그 수집은 **공식 `langfuse` SDK**.
- 비밀값(LangFuse public/secret key, host)은 `.env`/환경변수로 주입하고 저장소·로그에 남기지 않는다.
- 제안 디렉터리 레이아웃(부트스트랩에서 확정):

```
pyproject.toml
.python-version
.env.example              # 키 이름만 (값 없음)
app/
├── main.py               # Streamlit 진입점
├── config.py             # 설정 로딩(env → 키/host), 비밀값 미로깅
├── langfuse_client.py    # langfuse SDK 래퍼 (트레이스/generation 조회)
├── analysis/             # 분석·채점 (LLM-as-judge 등)
├── report/               # 리포트 조립·내보내기
└── testdata/             # 테스트 데이터 생성
```

## 작업 분할 (마일스톤 → 커밋 단위)

### M0 — 부트스트랩 (실행되는 빈 껍데기) ✅
- [x] `uv` 프로젝트 초기화: `pyproject.toml`, `.python-version`(3.12)
- [x] 의존성 추가: `streamlit`, `langfuse`, `pydantic-settings`(`python-dotenv` 전이 포함)
- [x] `app/main.py` 최소 Streamlit 화면 + `uv run streamlit run app/main.py` 기동 확인(헬스체크 통과)
- [x] `app/config.py` 로 LangFuse 키/host 를 env 에서 로딩(+ `.env.example`), `SecretStr` 로 미로깅

### M1 — 수집 ✅ (라이브 검증 통과: jp 리전 실프로젝트에서 트레이스 목록·상세 조회 확인)
- [x] `app/langfuse_client.py`: SDK(`client.api.trace.list`/`get`)로 트레이스/관측치 조회(이름·user·기간 필터)
- [x] Streamlit 에 트레이스 목록·상세 표시(input/output·모델·토큰). 키는 `SecretStr`, 본문은 화면에만

### M2 — 분석·점수·문제점 ✅ (코드; 라이브 채점은 OPENAI_API_KEY 확보 후)
- [x] 채점 기준·척도 정의 (7기준, 각 0~10 + overall)
- [x] 선택 트레이스 분석 → 점수·문제점 (OpenAI structured output, 기본 gpt-4o·설정형)
- [x] 결과 화면 표시 (점수표 + 문제점 목록)
- 상세 설계: [M2 분석·채점](2026-08-07-m2-분석-채점.md)

### M3 — 리포트
- [ ] 분석·점수·문제점을 리포트로 조립, 화면 표시 + 내보내기(md/json)

### M4 — 활용
- [ ] 리포트 기반 프롬프트 개선 방향 제안
- [ ] 리포트 기반 테스트 데이터 생성(스키마 정의 필요)

## 검증

- M0: `uv run streamlit run app/main.py` 로 로컬에서 화면이 뜨는지.
- M1: 실제(또는 샘플) LangFuse 프로젝트에서 트레이스 목록이 조회되는지.
- 각 마일스톤은 그 자체로 실행 가능한 상태를 유지(커밋 관례).

## 리스크·미결

- **LLM provider = OpenAI (잠정)**: 분석·채점·프롬프트 개선·테스트 데이터 생성에 OpenAI 를
  쓸 예정(사용자 잠정 결정, "쓸 것 같다"). M2 착수 시 모델·키 설정을 확정한다.
- **채점 기준(rubric)·점수 척도** 미정 — M2 전에 정의.
- **테스트 데이터 스키마** 미정 — M4 전에 정의.
- LangFuse 대량 트레이스의 페이지네이션·요청량. 초기엔 기간/개수 제한으로 시작.
- 로그 본문에 민감정보가 있을 수 있음 — 화면 표시는 하되 저장·재전송 경로에서 취급 주의.
