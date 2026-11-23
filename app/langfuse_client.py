"""LangFuse SDK 래퍼.

공식 ``langfuse`` Python SDK(v4)의 저수준 API(``client.api``)로 과거 트레이스와 관측치를
조회한다. 키는 [app.config][]에서 받아 SDK 생성자에만 넘기고, 값 자체는 로그·화면에 남기지
않는다. UI(app.main)는 이 모듈의 함수만 호출하고 SDK 세부에 직접 의존하지 않는다.

클라이언트는 **환경마다 하나씩** 만들어 둔다(→ [app.environments][]). SDK 는 내부 리소스를
public key 로 구분해 들고 있으므로 서로 다른 프로젝트의 클라이언트가 동시에 살아 있어도 된다.
조회 함수는 어느 프로젝트를 볼지 **`env` 로 반드시 받는다.** 기본값을 두면 환경을 빠뜨렸을 때
조용히 한쪽만 조회하게 된다.

**조회는 전부 v2 관측치 API(``GET /api/public/v2/observations``)로 한다.** 트레이스 목록·상세
API(``/api/public/traces``)는 LangFuse Cloud 에서 2026-11-16 에 없어졌다(410
``LANGFUSE_V3_API_REMOVED``). v2 에는 트레이스라는 단위가 없어 관측치를 ``traceId`` 로 묶어
트레이스를 다시 만든다.

- 트레이스의 이름·시각·latency·세션·입력·출력은 **루트 관측치**의 값이다. 대상 서버는 상위 서비스의
  span 아래에서 시작하므로 루트도 부모 id 를 갖고 있다. 그래서 부모가 비었는지가 아니라
  ``isRootObservation`` 으로 찾는다.
- 트레이스 비용은 그 트레이스 관측치의 ``totalCost`` 합이다.
- 입력·출력은 JSON **문자열**로 온다. 예전 상세처럼 dict 로 풀어 둔다.
- 결과는 늘 시작 시각 **내림차순**이고 정렬을 바꿀 수 없다. 오름차순이 필요한 수집은 시간 구간을
  나눠 부른다(→ [app.collect.sync][]).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from langfuse import Langfuse
from langfuse.api.core.api_error import ApiError

from app import environments
from app.config import get_settings

RATE_LIMIT_MAX_WAITS = 5
"""호출 한도(429)를 만났을 때 기다렸다가 다시 부르는 최대 횟수."""

RATE_LIMIT_DEFAULT_WAIT_SECONDS = 60.0
"""응답에 ``retry-after`` 가 없을 때 기다리는 시간."""

PAGE_LIMIT = 1000
"""v2 관측치 한 페이지 크기(API 최대값)."""

DETAIL_FIELDS = "core,basic,time,io,metadata,model,usage,metrics,trace_context"
"""트레이스 상세에 받는 필드 그룹. 단계 입출력(io)·단계 판정(metadata)·모델·토큰을 모두 쓴다."""

SUMMARY_FIELDS = "core,basic,metrics,trace_context"
"""목록 요약에 받는 루트 관측치 필드 그룹. 이름(traceName)·세션·latency 만 있으면 된다. 입력은 원본
데이터 전체라 무거워서 받지 않는다."""

COST_FIELDS = "core,usage"
"""비용 합산에 받는 필드 그룹(traceId·totalCost)."""

COST_SLACK = timedelta(hours=1)
"""루트가 구간 끝 직전에 시작하면 자식 관측치는 구간을 넘겨 시작한다. 비용은 이만큼 더 받아 합친다.
타임라인 생성은 몇 분이면 끝나므로 넉넉하다."""


@dataclass(frozen=True)
class Observation:
    """관측치 하나. 예전 트레이스 상세의 관측치와 같은 이름의 필드만 둔다(→ [app.tasks.trace_builder][])."""

    id: str
    trace_id: str | None
    parent_observation_id: str | None
    is_root_observation: bool | None
    type: str | None
    name: str | None
    level: str | None
    status_message: str | None
    start_time: datetime | None
    end_time: datetime | None
    latency: float | None
    metadata: Any
    input: Any
    output: Any
    model: str | None
    usage_details: dict[str, Any] | None
    total_cost: float | None


@dataclass(frozen=True)
class TraceSummary:
    """목록 한 줄에 필요한 트레이스 요약."""

    id: str
    name: str | None
    timestamp: datetime | None
    user_id: str | None
    session_id: str | None
    tags: list[str]
    latency: float | None
    total_cost: float


@dataclass(frozen=True)
class TraceDetail(TraceSummary):
    """예전 ``TraceWithFullDetails`` 자리. ``input``·``output`` 은 루트 관측치의 것이다."""

    input: Any = None
    output: Any = None
    metadata: Any = None
    observations: list[Observation] = field(default_factory=list)


class LangfuseNotConfigured(RuntimeError):
    """LangFuse 키가 없어 조회할 수 없을 때."""


class TraceNotFound(RuntimeError):
    """LangFuse 에 없는 트레이스. id 가 틀렸거나 보존 기간이 지났다."""


_clients: dict[str, Langfuse] = {}
"""환경 → 클라이언트. 키를 캐시 key 로 쓰지 않으려고 lru_cache 대신 이 표를 쓴다."""

_ENV_KEY_NAMES: dict[str, str] = {
    environments.DEV: "LANGFUSE_DEV_PUBLIC_KEY / LANGFUSE_DEV_SECRET_KEY",
    environments.PROD: "LANGFUSE_PROD_PUBLIC_KEY / LANGFUSE_PROD_SECRET_KEY",
}
"""환경별로 .env 에 필요한 변수 이름(안내 문구용)."""


def missing_credentials_message(env: str) -> str:
    """그 환경에 무엇을 설정해야 하는지 알려주는 문구."""
    names = _ENV_KEY_NAMES.get(env, f"LANGFUSE_{env.upper()}_PUBLIC_KEY / ..._SECRET_KEY")
    return (
        f"{environments.label(env)} 환경의 LangFuse 키가 없습니다. "
        f".env 에 {names} 를 설정하세요(.env.example 참고)."
    )


def get_client(env: str) -> Langfuse:
    """그 환경의 키로 Langfuse 클라이언트를 만든다(환경당 1회 캐시)."""
    resolved = environments.validate(env)
    client = _clients.get(resolved)
    if client is not None:
        return client

    credentials = get_settings().langfuse_credentials(resolved)
    if not credentials.is_complete:
        raise LangfuseNotConfigured(missing_credentials_message(resolved))
    # get_secret_value() 결과는 SDK 생성자에만 전달하고 어디에도 저장·로깅하지 않는다.
    client = Langfuse(
        public_key=credentials.public_key.get_secret_value(),
        secret_key=credentials.secret_key.get_secret_value(),
        host=credentials.host,
        # 이 도구는 LangFuse 를 읽기만 한다. 켜 두면 SDK 가 전역 OpenTelemetry 에 붙어, MCP 서버가
        # 도구 호출마다 만드는 span(gen_ai.* 속성)까지 그 프로젝트에 트레이스로 올린다.
        tracing_enabled=False,
    )
    _clients[resolved] = client
    return client


def _wait_on_rate_limit(call: Callable[[], Any]) -> Any:
    """호출 한도(429)에 걸리면 서버가 알려준 시간만큼 기다렸다가 다시 부른다.

    LangFuse 는 API 마다 분당 호출 수를 제한한다(2026-10 기준 v2 관측치 30회). 한도는 잠깐
    기다리면 풀리므로 실패로 올리지 않는다. 그래도 계속 막히면 마지막 오류를 그대로 올린다.
    """
    for _ in range(RATE_LIMIT_MAX_WAITS):
        try:
            return call()
        except ApiError as exc:
            if exc.status_code != 429:
                raise
            headers = {str(key).lower(): value for key, value in (exc.headers or {}).items()}
            try:
                seconds = float(headers.get("retry-after", RATE_LIMIT_DEFAULT_WAIT_SECONDS))
            except (TypeError, ValueError):
                seconds = RATE_LIMIT_DEFAULT_WAIT_SECONDS
            time.sleep(seconds + 1)
    return call()


def list_observations(*, env: str, **filters: Any) -> list[Any]:
    """v2 관측치를 마지막 페이지까지 받는다. ``filters`` 는 SDK ``observations.get_many`` 인자 그대로다.

    빈 페이지에도 커서가 붙어 올 수 있으므로 데이터가 아니라 커서가 없어질 때까지 부른다.
    """
    client = get_client(env)
    found: list[Any] = []
    cursor: str | None = None
    while True:
        page = _wait_on_rate_limit(
            lambda: client.api.observations.get_many(limit=PAGE_LIMIT, cursor=cursor, **filters)
        )
        found.extend(getattr(page, "data", None) or [])
        next_cursor = getattr(getattr(page, "meta", None), "cursor", None)
        if not next_cursor or next_cursor == cursor:
            return found
        cursor = next_cursor


def _decoded(value: Any) -> Any:
    """v2 가 문자열로 주는 입력·출력을 예전 상세처럼 풀어 준다. JSON 이 아니면 그대로 둔다."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _latency(observation: Any) -> float | None:
    """latency(초). 시작과 끝이 같으면 v2 는 비워서 주는데, 예전 목록은 0 이었다."""
    latency = getattr(observation, "latency", None)
    if latency is not None:
        return latency
    start = getattr(observation, "start_time", None)
    end = getattr(observation, "end_time", None)
    return (end - start).total_seconds() if start is not None and end is not None else None


def _started(observation: Any) -> tuple[bool, float]:
    """시작 시각 정렬 키. 시각이 없으면 맨 뒤."""
    start = getattr(observation, "start_time", None)
    return (start is None, start.timestamp() if start is not None else 0.0)


def _in_order(observations: list[Observation]) -> list[Observation]:
    """시작 시각 순. 같은 시각이면 부모를 먼저 둔다(루트와 첫 자식은 같은 밀리초에 시작하곤 한다)."""
    parents = {item.id: item.parent_observation_id for item in observations}

    def depth(item: Observation) -> int:
        seen: set[str] = set()
        current = item.parent_observation_id
        while current in parents and current not in seen:
            seen.add(current)
            current = parents[current]
        return len(seen)

    return sorted(observations, key=lambda item: (*_started(item), depth(item)))


def _root(observations: Iterable[Any]) -> Any:
    """트레이스의 루트 관측치.

    대상 서버는 상위 서비스 span 아래에서 시작해 루트도 부모 id 를 가진다. SDK 가 앱 루트로 표시한
    것을 먼저 보고, 없으면 부모가 트레이스 안에 없는 것을 본다. 대상 서버 테스트가 옛 트레이스 id 를
    재사용해 루트가 여럿인 경우가 있어, 여럿이면 가장 먼저 시작한 것을 쓴다.
    """
    items = list(observations)
    ids = {getattr(item, "id", None) for item in items}
    roots = [item for item in items if getattr(item, "is_root_observation", None)] or [
        item for item in items if getattr(item, "parent_observation_id", None) not in ids
    ]
    return min(roots or items, key=_started)


def _summary_fields(trace_id: str, root: Any, cost: float) -> dict[str, Any]:
    """루트 관측치와 비용 합으로 트레이스 요약을 만든다. 빈 문자열 user_id 는 예전처럼 None 으로 둔다."""
    return {
        "id": trace_id,
        "name": getattr(root, "trace_name", None) or getattr(root, "name", None),
        "timestamp": getattr(root, "start_time", None),
        "user_id": getattr(root, "user_id", None) or None,
        "session_id": getattr(root, "session_id", None) or None,
        "tags": list(getattr(root, "tags", None) or []),
        "latency": _latency(root),
        # 소수 합의 끝자리 오차 때문에 예전 값과 달라 보이지 않게 자른다.
        "total_cost": round(cost, 10),
    }


def observation_of(raw: Any) -> Observation:
    """SDK 의 v2 관측치 → [Observation][app.langfuse_client.Observation]. 입출력은 풀어 둔다."""
    level = getattr(raw, "level", None)
    return Observation(
        id=raw.id,
        trace_id=getattr(raw, "trace_id", None),
        parent_observation_id=getattr(raw, "parent_observation_id", None),
        is_root_observation=getattr(raw, "is_root_observation", None),
        type=getattr(raw, "type", None),
        name=getattr(raw, "name", None),
        level=getattr(level, "value", level),
        # 예전 상세는 상태 문구가 없으면 null 이었고 v2 는 빈 문자열을 준다. 채점 근거에 그대로 실리므로 맞춘다.
        status_message=getattr(raw, "status_message", None) or None,
        start_time=getattr(raw, "start_time", None),
        end_time=getattr(raw, "end_time", None),
        latency=_latency(raw),
        metadata=getattr(raw, "metadata", None),
        input=_decoded(getattr(raw, "input", None)),
        output=_decoded(getattr(raw, "output", None)),
        # 사람이 읽는 모델 이름은 응답의 model 칸에 온다(providedModelName 은 비어 오는 경우가 많다).
        model=getattr(raw, "model", None) or getattr(raw, "provided_model_name", None),
        usage_details=getattr(raw, "usage_details", None),
        total_cost=getattr(raw, "total_cost", None),
    )


def _costs_by_trace(from_timestamp: datetime, to_timestamp: datetime, env: str) -> dict[str, float]:
    """구간에 시작한 관측치 가운데 비용이 있는 것만 받아 traceId 별로 합친다.

    비용이 0 인 관측치는 합에 영향이 없다. 개발 프로젝트는 비용 0 인 테스트 관측치가 대부분이라
    걸러 받으면 호출이 크게 준다.
    """
    # filter 를 주면 시각 같은 개별 인자는 무시되므로 조건을 전부 filter 에 담는다.
    conditions = [
        {"type": "number", "column": "totalCost", "operator": ">", "value": 0},
        {"type": "datetime", "column": "startTime", "operator": ">=", "value": from_timestamp.isoformat()},
        {"type": "datetime", "column": "startTime", "operator": "<", "value": to_timestamp.isoformat()},
    ]
    costs: dict[str, float] = {}
    for observation in list_observations(env=env, filter=json.dumps(conditions), fields=COST_FIELDS):
        trace_id = getattr(observation, "trace_id", None)
        cost = getattr(observation, "total_cost", None)
        if trace_id and isinstance(cost, (int, float)):
            costs[trace_id] = costs.get(trace_id, 0.0) + float(cost)
    return costs


def has_traces(*, from_timestamp: datetime, to_timestamp: datetime, env: str) -> bool:
    """루트가 ``[from_timestamp, to_timestamp)`` 에 시작한 트레이스가 하나라도 있는지(호출 1번)."""
    client = get_client(env)
    page = _wait_on_rate_limit(
        lambda: client.api.observations.get_many(
            is_root_observation=True,
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            fields="core",
            limit=1,
        )
    )
    return bool(getattr(page, "data", None))


def list_traces(*, from_timestamp: datetime, to_timestamp: datetime, env: str) -> list[TraceSummary]:
    """루트가 ``[from_timestamp, to_timestamp)`` 에 시작한 트레이스 요약(최신순).

    루트 span 은 끝날 때 전송되므로 아직 도는 트레이스는 빠진다. 다음 수집이 다시 훑어 받는다.
    """
    roots: dict[str, Any] = {}
    for root in list_observations(
        env=env,
        is_root_observation=True,
        from_start_time=from_timestamp,
        to_start_time=to_timestamp,
        fields=SUMMARY_FIELDS,
    ):
        trace_id = getattr(root, "trace_id", None)
        if trace_id and (trace_id not in roots or _started(root) < _started(roots[trace_id])):
            roots[trace_id] = root
    if not roots:
        return []
    costs = _costs_by_trace(from_timestamp, to_timestamp + COST_SLACK, env)
    return [
        TraceSummary(**_summary_fields(trace_id, root, costs.get(trace_id, 0.0)))
        for trace_id, root in roots.items()
    ]


def get_trace(trace_id: str, env: str) -> TraceDetail:
    """트레이스 상세. 그 트레이스의 관측치를 전부 받아 시작 시각 순으로 묶는다.

    호출 한도에 걸리면 기다렸다가 다시 부르고, 관측치가 하나도 없으면
    [TraceNotFound][app.langfuse_client.TraceNotFound] 로 올린다.
    """
    raw = list_observations(env=env, trace_id=trace_id, fields=DETAIL_FIELDS)
    if not raw:
        raise TraceNotFound(
            f"LangFuse 에 없는 트레이스입니다: {trace_id} (id 가 틀렸거나 보존 기간이 지났습니다)"
        )
    root = _root(raw)
    cost = sum(
        float(item.total_cost)
        for item in raw
        if isinstance(getattr(item, "total_cost", None), (int, float))
    )
    return TraceDetail(
        **_summary_fields(trace_id, root, cost),
        input=_decoded(getattr(root, "input", None)),
        output=_decoded(getattr(root, "output", None)),
        metadata=getattr(root, "metadata", None),
        observations=_in_order([observation_of(item) for item in raw]),
    )


def list_generations(
    *,
    trace_id: str | None = None,
    from_start_time: datetime | None = None,
    to_start_time: datetime | None = None,
    limit: int = 100,
    cursor: str | None = None,
    env: str,
) -> Any:
    """GENERATION 관측치 목록(모델·토큰). 반환은 ``.data`` / ``.meta.cursor``.

    트레이스 요약에는 모델·토큰이 없다. 모델명과 토큰이 필요하면 이 함수로 관측치를 따로 조회한다.
    커서 기반 페이지네이션이라 다음 페이지는 ``meta.cursor`` 를 그대로 넘긴다.
    """
    client = get_client(env)
    return _wait_on_rate_limit(
        lambda: client.api.observations.get_many(
            trace_id=trace_id or None,
            type="GENERATION",
            fields="core,basic,model,usage",
            from_start_time=from_start_time,
            to_start_time=to_start_time,
            limit=limit,
            cursor=cursor or None,
        )
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
