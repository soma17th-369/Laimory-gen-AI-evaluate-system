# 2026-09-18 Claude Code CLI Provider 추가

## 한 일

- 모든 LLM 기능이 Codex CLI(기본)나 deprecated OpenAI API로만 돌던 것을, `LLM_PROVIDER=claude`로
  로컬 Claude Code CLI(`claude -p`)에서도 돌 수 있게 `ClaudeCodeProvider`를 추가했다.
- 설정에 `CLAUDE_MODEL`, `CLAUDE_TIMEOUT_SECONDS`를 더했다. provider 표시명·준비 상태 안내·
  오류 코드(`CLAUDE_NOT_INSTALLED`, `CLAUDE_NOT_AUTHENTICATED`, `CLAUDE_EXECUTION_FAILED`,
  `CLAUDE_TIMEOUT`)를 Codex와 같은 형태로 맞췄다. 상위 호출부·UI는 바꾸지 않았다.

## 결정과 근거

- API key 방식(Anthropic SDK)이 아니라 CLI 방식을 골랐다. Codex 전환의 이유였던 "계정 로그인으로
  돌리고 API key를 쓰지 않는다"를 그대로 따른다.
- 실행 옵션은 Codex의 격리 원칙에 맞췄다: `-p --output-format json --no-session-persistence
  --safe-mode --tools ""`, cwd는 빈 임시 디렉터리. `--safe-mode`는 사용자 CLAUDE.md·hook·MCP·
  플러그인을 끄지만 인증·모델 선택은 그대로 둔다. `--bare`는 OAuth를 읽지 않아(API key 전용)
  구독 로그인으로는 쓸 수 없다.
- 시스템 프롬프트는 `--system-prompt-file`로 Claude Code 기본 프롬프트를 **대체**한다. Codex처럼
  지시를 stdin 한 덩어리에 감싸지 않고 system/user를 나눠 둔다. 단계 채점 system prompt가 최대
  약 15K자, 스키마가 최대 약 7K자라 둘 다 명령줄 인자로 넘기면 Windows 명령줄 한도(32K)에 가깝다.
- `--json-schema`는 **인라인 JSON만** 받는다(파일 경로를 주면 `--json-schema is not valid JSON`).
  그래서 스키마만 인자로, 나머지는 파일·stdin으로 넘긴다. 공백 없는 compact JSON으로 줄였다.
- 인증 확인은 `claude auth status`(기본 JSON 출력)의 `loggedIn`만 읽는다. 출력에 이메일·조직 ID가
  들어 있으므로 다른 값은 어디에도 남기지 않는다.

## 실물 포맷 확인 (구현 전에 CLI로 직접 확인)

- 성공 envelope: `type=result, subtype=success, is_error=false, result=<최종 텍스트>`. 구조화
  출력이면 `structured_output`에 파싱된 객체가, `result`에 같은 JSON 문자열이 온다. 내부적으로
  구조화 출력용 도구를 한 번 쓰기 때문에 `num_turns=2`, `stop_reason=tool_use`다.
- 실패 envelope: 종료 코드 1, **stderr는 비고** stdout에 `is_error=true, result=<오류 문구>`가 온다.
  그래서 오류 문구는 stderr가 아니라 envelope의 `result`에서 읽는다.
- `$ref`/`$defs`가 있는 실제 단계 채점 스키마(`calibration.result_model`)를 그대로 받아들였고,
  돌아온 `structured_output`이 같은 Pydantic 모델 검증을 통과했다.
- Python `subprocess`(utf-8)로 넘긴 한국어 입력·출력이 깨지지 않았다(Git Bash `echo` 파이프로
  넣었을 때만 콘솔 코드페이지 탓에 깨져 보였다).
- 이 계정의 CLI 기본 모델은 `claude-fable-5-1`이었다.

## 검증

- Claude provider 단위 테스트 10개 추가(격리 옵션, 텍스트·구조화, 기본 모델, 미설치·미인증·
  timeout·오류 envelope·인증 오류 envelope·JSON/스키마 불일치, provider 선택·표시명·준비 상태).
- 전체 unittest 184개 통과.
- `LLM_PROVIDER=claude`로 실제 호출: `generate_text` 약 9초, question 단계 실채점
  (`stage_judge.score_evidence`) 약 108초에 스키마 검증 통과, 근거 없는 동행 인물이 든 질문에서
  event_grounding 감점을 확인했다.

## 막힌 점 / 열린 질문

- 첫 실호출에서 `Failed to refresh OAuth token: another Claude Code process is refreshing it`
  오류가 두 번 났다가 저절로 풀렸다. 같은 계정의 다른 Claude Code 프로세스와 토큰 갱신이 겹친
  일시 오류다. 인증 오류로 분류하지 않고 `CLAUDE_EXECUTION_FAILED`로 CLI 문구를 그대로 보여 준다.
  단계 병렬 채점(기본 3 worker)에서 자주 나면 재시도를 검토한다.
- npm 설치(`claude.cmd` shim)는 검증하지 않았다. `.cmd`는 `cmd.exe`를 거치므로 인라인 JSON
  인자의 따옴표·길이(8191자) 제한에 걸릴 수 있다. 네이티브 설치를 전제로 README에 적었다.
- `scripts/check_judge_repeatability.py`는 여전히 `CodexProvider`를 직접 만든다(실험 스크립트라
  그대로 둠).

## 다음 할 일

- 필요하면 화면에서 provider를 바꾸는 선택지(지금은 `.env` + 앱 재시작).
- 같은 trace를 Codex·Claude로 각각 채점해 점수 분포·지연 시간을 비교한다.
