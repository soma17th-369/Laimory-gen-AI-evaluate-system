# 2026-08-30 Codex CLI Judge

> 이 기록 이후 같은 날 후속 작업에서 개선책·테스트 데이터 생성도 공통 Codex Provider로
> 전환했다. 현재 상태는 `2026-08-30-all-llm-codex-provider.md`를 참고한다.

## 한 일

- 기존 `score_trace`의 OpenAI API 직접 호출을 `JudgeProvider` 경계 뒤로 옮겼다.
- 기본 `CodexJudgeProvider`는 `codex login status` 확인 후 빈 임시 디렉터리에서
  `codex exec --ephemeral --sandbox read-only --output-schema ... -`를 실행한다.
- 현재 `TraceScorecard`의 Pydantic JSON Schema를 strict object schema로 만들어 전달하고, 최종
  JSON을 같은 모델로 다시 검증한다.
- 기존 호출은 `OpenAIApiJudgeProvider`로 보존하고 deprecated 경고를 추가했다. 자동 fallback은
  두지 않았다.
- provider·Codex 모델·timeout 설정과 Task 리뷰 UI의 setup/error 안내를 추가했다.
- README, 환경변수 예시, 시스템 개요와 공통 용어를 새 기본 경로에 맞췄다.

## 결정과 근거

- ChatGPT 앱 UI 자동화 대신 공식 비대화형 CLI를 subprocess로 호출한다. 공식 OpenAI 문서와 설치된
  CLI 모두 stdin 전체 prompt, ephemeral 실행, output schema, last-message 파일 출력을 지원했다.
- CLI 기본 모델을 코드에 중복 하드코딩하지 않는다. `CODEX_JUDGE_MODEL`이 비어 있으면 Codex CLI의
  기본 모델을 쓰고, 재현성이 필요할 때만 명시한다.
- repository 규칙·파일 탐색에 평가가 흔들리지 않도록 실제 저장소가 아닌 빈 임시 디렉터리를 cwd로
  사용한다. read-only sandbox와 prompt 지시도 함께 적용한다.
- ChatGPT 인증 여부는 CLI의 `codex login status` 종료 코드로 확인한다. 인증 방식 감지나 API key
  차단은 애플리케이션 책임으로 만들지 않았다.
- 개선책·테스트 데이터 생성은 이번 범위가 Judge 변경뿐이므로 기존 OpenAI API 호출을 유지했다.

## 검증

- Provider 선택·오류·structured output과 deprecated OpenAI provider 회귀를 포함한 전체 unittest
  69개가 통과했다.
- 로컬 `codex-cli 0.150.1`, `Logged in using ChatGPT` 확인.
- Codex sandbox 안에서는 사용자 Codex state DB 쓰기가 막혀 최초 smoke test가 실패했으나, 정상 사용자
  권한으로 재실행해 `--output-schema` 결과 `{"score": 7, ...}`을 받고 Pydantic 검증까지 통과했다.

## 막힌 점 / 열린 질문

- 실제 전체 `TraceScorecard` 채점의 latency와 ChatGPT 사용량은 대표 trace로 운영 확인이 필요하다.
- 개선책·테스트 데이터 생성도 같은 provider로 옮길지는 별도 범위다.

## 다음 할 일

- 최종 전체 테스트와 diff 검증 후 계획 상태를 완료로 바꾼다.
