"""수집 대상 LangFuse 프로젝트(**환경**) — 환경 키와 표기.

이 도구는 LangFuse 프로젝트를 둘 다룬다(개발 `dev` · 운영 `prod`). 둘은 **갈라 보지 않는다.**
수집한 로그는 한 목록에 시간순으로 함께 늘어놓고, 어느 프로젝트에서 온 것인지는 행마다 붙는
`env` 값으로 구분한다. 저장 경로도 화면도 환경으로 쪼개지 않는다(→ [app.storage.paths][]).

환경이 실제로 갈리는 자리는 셋뿐이다.

1. **자격증명** — 프로젝트마다 키가 다르다(→ [app.config][]).
2. **클라이언트** — 키가 다르니 조회 클라이언트도 환경마다 하나(→ [app.langfuse_client][]).
3. **동기화 커서** — "어디까지 훑었는지"는 프로젝트마다 다르다(→ [app.collect.sync][]).

그 셋은 환경을 **명시적으로 받는다**. 기본값을 두지 않는 이유는, 환경을 빠뜨렸을 때 조용히
한쪽을 조회하는 것보다 바로 드러나는 편이 낫기 때문이다.
"""

from __future__ import annotations

from typing import Any

DEV = "dev"
PROD = "prod"

ENVIRONMENTS: tuple[str, ...] = (DEV, PROD)
"""화면 표기 순서이자 허용 값의 전부. 새 환경을 늘리려면 여기에 키를 추가한다."""

LABELS: dict[str, str] = {
    DEV: "개발 (dev)",
    PROD: "운영 (prod)",
}
"""환경 키 → 화면 라벨. 화면은 이 표만 쓰고 문자열을 따로 만들지 않는다."""

SHORT_LABELS: dict[str, str] = {
    DEV: "dev",
    PROD: "prod",
}
"""표 한 칸에 들어갈 짧은 표기."""


class UnknownEnvironment(ValueError):
    """알 수 없는 환경 키를 넘겼을 때."""


def label(env: str) -> str:
    """화면 라벨. 모르는 키면 키를 그대로 보여준다."""
    return LABELS.get(env, env)


def short_label(env: str) -> str:
    """표 한 칸용 짧은 표기."""
    return SHORT_LABELS.get(env, env)


def validate(env: str) -> str:
    """허용된 환경 키인지 확인하고 그대로 돌려준다."""
    if env not in ENVIRONMENTS:
        raise UnknownEnvironment(
            f"알 수 없는 환경입니다: {env!r} (가능한 값: {', '.join(ENVIRONMENTS)})"
        )
    return env


def of(record: Any) -> str:
    """저장된 행·레코드가 어느 환경에서 왔는지.

    `env` 가 없는 것은 환경 구분이 생기기 전에 수집한 데이터라 `dev` 로 본다. 그때는 개발
    프로젝트 하나만 보고 있었다.
    """
    if isinstance(record, dict):
        value = record.get("env")
        if value in ENVIRONMENTS:
            return str(value)
    return DEV
