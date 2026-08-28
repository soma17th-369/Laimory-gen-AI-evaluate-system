"""LangFuse SDK 래퍼.

공식 ``langfuse`` Python SDK(v4)의 저수준 API(``client.api``)로 과거 트레이스와 관측치를
조회한다. 키는 [app.config][]에서 받아 SDK 생성자에만 넘기고, 값 자체는 로그·화면에 남기지
않는다. UI(app.main)는 이 모듈의 함수만 호출하고 SDK 세부에 직접 의존하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, Sequence

from langfuse import Langfuse

from app.config import get_settings


class LangfuseNotConfigured(RuntimeError):
    """LangFuse 키가 없어 조회할 수 없을 때."""


@lru_cache
def get_client() -> Langfuse:
    """설정의 키로 Langfuse 클라이언트를 만든다(프로세스당 1회 캐시)."""
    settings = get_settings()
    if not settings.has_langfuse_credentials():
        raise LangfuseNotConfigured(
            "LangFuse 키가 없습니다. .env 에 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 를 "
            "설정하세요(.env.example 참고)."
        )
    # get_secret_value() 결과는 SDK 생성자에만 전달하고 어디에도 저장·로깅하지 않는다.
    return Langfuse(
        public_key=settings.langfuse_public_key.get_secret_value(),
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )


def list_traces(
    *,
    limit: int = 50,
    page: int = 1,
    name: str | None = None,
    user_id: str | None = None,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    order_by: str | None = None,
    fields: str | None = None,
    tags: Sequence[str] | None = None,
) -> Any:
    """트레이스 목록(페이지 1건)을 조회한다. 반환은 SDK 의 ``Traces``(``.data`` / ``.meta``).

    ``order_by`` 는 ``"[field].[asc|desc]"`` 형식(예: ``"timestamp.asc"``). 생략하면 SDK 기본 정렬.
    ``fields`` 는 응답에 담을 필드 그룹(``core``/``io``/``scores``/``observations``/``metrics``)을
    콤마로 나열한다. 생략하면 전부 받는다(트레이스당 관측치까지 실려 목록 조회가 느려진다).
    """
    client = get_client()
    return client.api.trace.list(
        page=page,
        limit=limit,
        name=name or None,
        user_id=user_id or None,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        order_by=order_by or None,
        fields=fields or None,
        tags=list(tags) if tags else None,
    )


def get_trace(trace_id: str) -> Any:
    """트레이스 상세(관측치·스코어 포함, ``TraceWithFullDetails``)를 조회한다."""
    return get_client().api.trace.get(trace_id)


def list_generations(
    *,
    trace_id: str | None = None,
    from_start_time: datetime | None = None,
    to_start_time: datetime | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> Any:
    """GENERATION 관측치 목록(모델·토큰). 반환은 ``.data`` / ``.meta.cursor``.

    트레이스 목록 API 는 모델·토큰을 주지 않는다(``observations`` 가 id 목록뿐). 모델명과 토큰이
    필요하면 이 함수로 관측치를 따로 조회한다. 커서 기반 페이지네이션이라 다음 페이지는
    ``meta.cursor`` 를 그대로 넘긴다.
    """
    return get_client().api.observations.get_many(
        trace_id=trace_id or None,
        type="GENERATION",
        fields="core,basic,model,usage",
        from_start_time=from_start_time,
        to_start_time=to_start_time,
        limit=limit,
        cursor=cursor or None,
    )


# --- UI 표시용 매핑 (SDK 모델 → 얇은 dict) -------------------------------------

def trace_summary(trace: Any) -> dict[str, Any]:
    """목록 표 한 줄. 필드가 없으면 None 으로 둔다(SDK 버전차 방어)."""
    obs = getattr(trace, "observations", None)
    return {
        "timestamp": getattr(trace, "timestamp", None),
        "name": getattr(trace, "name", None),
        "user_id": getattr(trace, "user_id", None),
        "latency": getattr(trace, "latency", None),
        "total_cost": getattr(trace, "total_cost", None),
        "observations": len(obs) if obs is not None else None,
        "id": getattr(trace, "id", None),
    }


def observation_total_tokens(obs: Any) -> int | None:
    """관측치의 총 토큰 수. usage.total 우선, 없으면 usage_details 합, 그것도 없으면 None."""
    usage = getattr(obs, "usage", None)
    total = getattr(usage, "total", None) if usage is not None else None
    if total is not None:
        return total
    details = getattr(obs, "usage_details", None)
    if isinstance(details, dict):
        nums = [v for v in details.values() if isinstance(v, (int, float))]
        if nums:
            return int(sum(nums))
    return None


def observation_row(obs: Any) -> dict[str, Any]:
    """관측치 표 한 줄."""
    obs_type = getattr(obs, "type", None)
    return {
        "type": getattr(obs_type, "value", obs_type),
        "name": getattr(obs, "name", None),
        "model": getattr(obs, "model", None),
        "tokens": observation_total_tokens(obs),
        "latency": getattr(obs, "latency", None),
        "id": getattr(obs, "id", None),
    }
