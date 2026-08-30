# 2026-08-30 모든 LLM 기능 Codex Provider 전환

## 한 일

- Judge 전용 Provider를 `LlmProvider` 계약과 `CodexProvider` 구현으로 일반화했다.
- `generate_structured`는 Pydantic JSON Schema를 `codex exec --output-schema`에 전달하고 결과를
  같은 모델로 재검증한다. `generate_text`는 `--output-last-message`의 일반 텍스트를 반환한다.
- 채점, 프롬프트 개선 제안, 개선책 본문, 채점 결과 기반 테스트 케이스, 개선책 기반 테스트
  케이스를 모두 `get_llm_provider()` 경계로 옮겼다.
- 모든 관련 UI가 공통 Provider 표시명·준비 상태·오류 코드를 사용하게 했다. 기본 Codex 설정에서
  `OPENAI_API_KEY` 유무로 버튼을 막지 않는다.
- 공통 설정을 `LLM_PROVIDER`, `CODEX_MODEL`, `CODEX_TIMEOUT_SECONDS`로 정리했다.
- 기존 API 구현은 자동 fallback 없는 deprecated `OpenAIApiProvider`로만 남겼다.

## 결정과 근거

- 상위 기능은 특정 SDK를 직접 알지 않는다. 실행 방식 변경과 오류 처리는 Provider 한 곳에서만
  맡는다.
- 구조화 출력이 필요한 기능은 기존 Pydantic 도메인 모델을 유지했다. JSON 형식 강제와 로컬
  검증을 함께 써 호출 경로 변경이 저장 계약을 바꾸지 않게 했다.
- 자유 형식 개선책은 불필요한 JSON wrapper 없이 Codex 최종 메시지 그대로 받는다.
- Codex 실패 시 OpenAI API로 자동 전환하지 않는다. 따라서 기본 설정에서 API key가 로컬에 남아
  있어도 이 애플리케이션이 그 키로 호출하지 않는다.

## 검증

- Provider 일반 텍스트·구조화 출력과 네 상위 호출부 라우팅 테스트를 추가했다.
- 전체 unittest 74개 통과.
- `app/` 검색 결과 `get_openai_client`와 `chat.completions`는 deprecated Provider 내부에만 남았다.
- 로그인된 Codex CLI로 일반 텍스트 실호출이 종료 코드 0과 비어 있지 않은 최종 결과를 반환했다.
- `git diff --check` 통과(Windows CRLF 변환 안내만 출력).

## 막힌 점 / 열린 질문

- OpenAI SDK 의존성은 deprecated Provider 호환을 위해 남아 있다. 이를 완전히 제거하려면 별도
  호환성 중단 결정이 필요하다.
- 모든 Codex 호출은 같은 ChatGPT/Codex 사용 한도를 공유한다.

## 다음 할 일

- 대표 실제 trace로 채점·개선책·테스트 데이터 전체 흐름의 지연 시간과 사용 한도를 운영 확인한다.
