"""타임라인 AI 테스트 엔드포인트 호출 — `POST /t/api/{applicationVersion}/timeline/test`.

dev 서버 전용이다. 서버는 AI 추론이 끝날 때까지 **동기로** 붙잡고 있다가(수십 초 ~ 약 150초)
결과를 돌려준다. 실제 LLM 토큰 비용이 들고, 실패해도 서버·이 도구 모두 **자동 재시도하지 않는다.**

응답 두 모양:

- 200 — envelope 없이 `{taskId, timedOut, events[]}`. `timedOut: true` 는 AI 가 제한 시간(120초)에
  걸려 마지막 확정본을 돌려줬다는 뜻이지 실패가 아니다.
- 그 외 — `{"header": {"code", "message"}, "body": null}`. 502 에서 AI 가 응답을 줬으면
  `X-Ai-Error-Code` 헤더에 AI 쪽 코드가 온다. 헤더가 없으면 AI 응답 자체를 못 받은 경우다.

URL·토큰은 `.env` 의 `TIMELINE_TEST_URL`·`TIMELINE_TEST_ACCESS_TOKEN` 에서 읽고(→ [app.config][]),
토큰은 `Authorization: Bearer` 헤더로만 나간다. 결과·기록 어디에도 토큰을 남기지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.devtest import request

AI_ERROR_CODES: dict[str, str] = {
    "1001": "필수값 누락",
    "1003": "AI 쪽에서 기능이 꺼져 있음",
    "1102": "원본 데이터 계약 위반",
    "1201": "제한 시간 안에 확정 결과 없음",
    "1202": "구조화 출력 실패",
    "1301": "입력에 없는 rawId 를 참조",
}
"""`X-Ai-Error-Code` 헤더 값 → 뜻."""

STATUS_MEANINGS: dict[int, str] = {
    400: "요청 형식 오류",
    401: "인증 실패 — access token 을 확인하세요",
    403: "권한 없음 — access token 을 확인하세요",
    404: "이 환경에서 기능이 꺼져 있거나 URL 이 틀림",
    502: "AI 처리 실패",
}

_CONNECT_TIMEOUT_SECONDS = 5.0
_TEXT_LIMIT = 4000
"""JSON 이 아닌 응답(프록시 HTML 등)은 앞부분만 남긴다."""


@dataclass(frozen=True)
class Endpoint:
    """호출 대상. 토큰은 ``SecretStr`` 로만 들고 다닌다."""

    url: str
    access_token: SecretStr | None
    timeout_seconds: float

    @property
    def has_token(self) -> bool:
        return self.access_token is not None


def endpoint_from_settings(settings: Settings | None = None) -> Endpoint | None:
    """`.env` 설정으로 호출 대상을 만든다. URL 이 없으면 None."""
    settings = settings or get_settings()
    url = (settings.timeline_test_url or "").strip()
    if not url:
        return None
    token = settings.timeline_test_access_token
    if token is not None and not token.get_secret_value().strip():
        token = None
    return Endpoint(
        url=url,
        access_token=token,
        timeout_seconds=float(settings.timeline_test_timeout_seconds),
    )


@dataclass(frozen=True)
class Outcome:
    """호출 한 번의 결과. `status` 가 None 이면 응답을 받지 못한 것(시간 초과·연결 실패)."""

    status: int | None
    elapsed_seconds: float
    body: Any = None
    """JSON 응답 — 200 이면 결과 본문, 그 외에는 에러 envelope."""
    text: str | None = None
    """JSON 이 아닌 응답의 원문(앞부분)."""
    ai_error_code: str | None = None
    transport_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and isinstance(self.body, dict)

    @property
    def _header(self) -> dict[str, Any]:
        header = self.body.get("header") if isinstance(self.body, dict) else None
        return header if isinstance(header, dict) else {}

    @property
    def error_code(self) -> Any:
        return self._header.get("code")

    @property
    def error_message(self) -> str | None:
        message = self._header.get("message")
        return str(message) if message is not None else None

    @property
    def task_id(self) -> str | None:
        value = self.body.get("taskId") if self.ok else None
        return str(value) if value else None

    @property
    def timed_out(self) -> bool:
        return bool(self.ok and self.body.get("timedOut"))

    @property
    def events(self) -> list[dict[str, Any]]:
        events = self.body.get("events") if self.ok else None
        return [event for event in events or [] if isinstance(event, dict)]

    def failure_text(self) -> str:
        """실패를 한 줄로. 성공이면 빈 문자열."""
        if self.ok:
            return ""
        if self.status is None:
            return f"응답 없음 — {self.transport_error or '알 수 없는 전송 오류'}"
        parts = [f"HTTP {self.status}"]
        meaning = STATUS_MEANINGS.get(self.status)
        if meaning:
            parts.append(meaning)
        if self.error_code is not None or self.error_message:
            parts.append(f"code {self.error_code}: {self.error_message or '-'}")
        if self.ai_error_code:
            ai_meaning = AI_ERROR_CODES.get(self.ai_error_code, "명세에 없는 코드")
            parts.append(f"AI {self.ai_error_code} {ai_meaning}")
        elif self.status == 502:
            parts.append("AI 응답을 받지 못함(X-Ai-Error-Code 없음)")
        return " · ".join(parts)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> Outcome:
        return cls(
            status=record.get("status"),
            elapsed_seconds=float(record.get("elapsed_seconds") or 0.0),
            body=record.get("body"),
            text=record.get("text"),
            ai_error_code=record.get("ai_error_code"),
            transport_error=record.get("transport_error"),
        )


def send(
    endpoint: Endpoint,
    body: Any,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Outcome:
    """요청을 한 번 보낸다. 예외를 던지지 않고 결과를 [Outcome][app.devtest.client.Outcome] 으로 돌려준다."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if endpoint.access_token is not None:
        headers["Authorization"] = f"Bearer {endpoint.access_token.get_secret_value().strip()}"
    timeout = httpx.Timeout(endpoint.timeout_seconds, connect=_CONNECT_TIMEOUT_SECONDS)
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.post(endpoint.url, content=request.encode(body), headers=headers)
    except httpx.TimeoutException as exc:
        return Outcome(
            status=None,
            elapsed_seconds=time.monotonic() - started,
            transport_error=f"시간 초과({endpoint.timeout_seconds:.0f}초, {type(exc).__name__})",
        )
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return Outcome(
            status=None,
            elapsed_seconds=time.monotonic() - started,
            transport_error=f"{type(exc).__name__}: {exc}",
        )
    elapsed = time.monotonic() - started
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    return Outcome(
        status=response.status_code,
        elapsed_seconds=elapsed,
        body=parsed,
        text=None if parsed is not None else response.text[:_TEXT_LIMIT],
        ai_error_code=response.headers.get("X-Ai-Error-Code"),
    )
