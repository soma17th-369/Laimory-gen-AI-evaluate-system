# 모든 LLM 기능 Codex Provider 전환

- 상태: 완료
- 관련 이슈:

## 배경·목표

Judge만 Codex CLI를 쓰고 개선책·테스트 데이터 생성은 OpenAI API를 직접 호출하는 혼합 상태를
없앤다. 모든 상위 LLM 기능이 하나의 Provider 경계를 사용하고 기본 설정에서 전부 `codex exec`로
실행되게 한다.

## 범위 / 범위 밖

- 포함: Codex Provider의 일반 텍스트·구조화 출력 지원, 채점·프롬프트 개선·개선책·테스트 데이터
  생성 전환, 공통 설정·UI 상태 안내, 직접 API 호출 제거 검증, 테스트·문서 갱신.
- 범위 밖: 기존 deprecated OpenAI provider 삭제, API key 강제 제거·차단, Codex 로그인 flow 구현.

## 접근

- `LlmProvider`에 `generate_text`와 `generate_structured`를 두고 `CodexProvider`가 두 경로를 모두
  같은 격리·timeout·오류 처리로 실행한다.
- 구조화 기능은 기존 Pydantic 모델을 `--output-schema`로 전달하고 재검증한다. 자유 형식 개선책은
  최종 메시지 파일을 일반 텍스트로 읽는다.
- 모든 UI는 공통 provider 준비 상태와 표시명을 사용한다. 기본 provider에서는
  `OPENAI_API_KEY` 유무로 버튼을 막지 않는다.

## 작업 분할

- [x] 공통 LLM Provider·설정으로 일반화
- [x] 개선책·테스트 데이터 호출 및 UI 전환
- [x] 단위 테스트·직접 호출 검색·Codex smoke test
- [x] README·Knowledge·Worklog 갱신

## 검증

- Provider 일반 텍스트·구조화 출력 단위 테스트.
- 상위 네 호출부가 공통 Provider 메서드를 사용하는 테스트.
- `app/`에서 deprecated provider 내부 외 `chat.completions` 직접 호출이 없는지 검색.
- 전체 unittest와 Codex CLI 일반 텍스트 실호출.

## 리스크·미결

- 모든 기능이 ChatGPT/Codex 사용 한도를 공유한다.
- deprecated OpenAI provider를 명시적으로 선택하면 기존과 같이 API 과금 가능성이 있다.
