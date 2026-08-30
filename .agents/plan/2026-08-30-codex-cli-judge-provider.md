# Codex CLI Judge Provider

> 후속 작업에서 Judge 전용 경계를 모든 LLM 기능의 공통 `CodexProvider`로 확장했다.
> 현재 설정과 범위는 `2026-08-30-all-llm-codex-provider.md`가 정본이다.

- 상태: 완료
- 관련 이슈:

## 배경·목표

로컬 LLM-as-a-Judge의 기본 실행 경로를 OpenAI API 직접 호출에서, 사용자가 ChatGPT 계정으로
인증한 Codex CLI의 비대화형 `codex exec` 호출로 바꾼다. 기존 `TraceScorecard` 계약과 rubric은
유지하고 OpenAI API 구현은 명시적으로 선택할 수 있는 deprecated provider로 남긴다.

## 범위 / 범위 밖

- 포함: Judge Provider 추상화, Codex CLI subprocess 실행, 기존 Pydantic JSON Schema 재사용,
  provider·모델·timeout 설정, 구분 가능한 실행 오류, Task 리뷰 UI와 설정 안내, 단위·실행 검증.
- 범위 밖: ChatGPT 로그인 flow 구현, API key 사용 차단, Codex 실패 시 OpenAI API 자동 fallback,
  개선책·테스트 데이터 생성 호출의 provider 전환, 기존 평가 스키마 재설계.

## 접근

- 상위 채점 로직은 provider를 선택해 `TraceScorecard`만 받도록 유지한다.
- Codex provider는 격리된 임시 디렉터리에서 read-only·ephemeral 실행하고, 전체 프롬프트를 stdin으로
  전달한다.
- `TraceScorecard.model_json_schema()`를 strict object schema로 정규화해 `--output-schema`에 넘기고,
  최종 메시지를 JSON으로 읽은 뒤 Pydantic으로 다시 검증한다.
- OpenAI provider는 기존 `chat.completions.parse` 동작을 옮기되 deprecated 경고를 남긴다.

## 작업 분할

- [x] Provider와 설정 추가, 기본 provider를 Codex로 변경
- [x] Task 리뷰 UI·README·환경변수 예시 갱신
- [x] Provider 단위 테스트와 로컬 Codex CLI smoke test
- [x] Worklog·Knowledge 갱신

## 검증

- provider 선택, CLI 미설치·미인증·실행 실패·timeout·잘못된 JSON·schema 불일치 단위 테스트.
- 전체 unittest 회귀 테스트.
- 설치된 Codex CLI의 버전·인증 상태 및 `--output-schema`를 사용한 최소 실호출 확인.

## 리스크·미결

- ChatGPT 플랜의 실제 사용량·rate limit은 Codex가 관리하며 애플리케이션이 보장하지 않는다.
- `CODEX_JUDGE_MODEL`을 비우면 Codex CLI의 현재 기본 모델을 사용하므로 재현성이 필요할 때는 명시한다.
