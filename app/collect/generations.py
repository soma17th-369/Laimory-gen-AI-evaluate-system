"""트레이스별 **모델·토큰 롤업** — 목록 API 에 없는 정보만 따로 모아 캐시한다.

`collection.json` 의 행에는 모델과 토큰이 없다. LangFuse 트레이스 목록 API 가 주지 않기
때문이다(`observations` 필드는 관측치 id 목록뿐). 그래서 필요할 때만 GENERATION 관측치를
트레이스 단위로 조회해 아래 형태로 `data/generations.json` 에 쌓는다.

```json
{
  "<traceId>": {
    "models": ["gpt-5.4-mini"],
    "generations": 10,
    "inputTokens": 118143,
    "outputTokens": 18155,
    "totalTokens": 136298,
    "cost": 0.145
  }
}
```

한 번 조회한 트레이스는 다시 조회하지 않는다. 트레이스는 끝난 뒤에는 바뀌지 않으므로 캐시를
무효화할 일이 없다.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from app.langfuse_client import list_generations
from app.storage import store
from app.storage.paths import generation_rollup_file

_PAGE = 100
_MAX_PAGES = 20
"""트레이스 하나가 가질 수 있는 관측치 페이지 상한(무한 루프 방지)."""


def load_rollup() -> dict[str, dict[str, Any]]:
    """캐시 전체. 없거나 깨졌으면 빈 dict."""
    data = store.load_json(generation_rollup_file())
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _tokens(usage: Any) -> tuple[int, int, int]:
    """usage_details → (input, output, total). total 이 없으면 input+output 으로 채운다."""
    if not isinstance(usage, dict):
        return 0, 0, 0
    def value(key: str) -> int:
        raw = usage.get(key)
        return int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0

    input_tokens = value("input")
    output_tokens = value("output")
    total = value("total") or (input_tokens + output_tokens)
    return input_tokens, output_tokens, total


def _model_name(observation: Any) -> str | None:
    """읽을 수 있는 모델명. 없으면 None.

    관측치에서 사람이 읽는 이름은 ``model``(예: ``gpt-5.4-mini``)에 있다. ``model_id`` /
    ``internal_model_id`` 는 LangFuse 내부 UUID 라 화면에 쓰지 않는다. ``provided_model_name``
    은 비어 있는 경우가 많아 보조로만 본다.
    """
    for key in ("model", "provided_model_name"):
        value = getattr(observation, key, None)
        if value:
            return str(value)
    return None


def fetch_trace(trace_id: str) -> dict[str, Any]:
    """트레이스 하나의 GENERATION 관측치를 모아 롤업 한 건을 만든다."""
    models: list[str] = []
    generations = 0
    input_tokens = output_tokens = total_tokens = 0
    cost = 0.0

    cursor: str | None = None
    for _ in range(_MAX_PAGES):
        response = list_generations(trace_id=trace_id, limit=_PAGE, cursor=cursor)
        batch = getattr(response, "data", []) or []
        for observation in batch:
            generations += 1
            name = _model_name(observation)
            if name and name not in models:
                models.append(name)
            got_in, got_out, got_total = _tokens(getattr(observation, "usage_details", None))
            input_tokens += got_in
            output_tokens += got_out
            total_tokens += got_total
            observation_cost = getattr(observation, "total_cost", None)
            if isinstance(observation_cost, (int, float)):
                cost += float(observation_cost)
        cursor = getattr(getattr(response, "meta", None), "cursor", None)
        if not batch or not cursor:
            break

    return {
        "models": models,
        "generations": generations,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cost": round(cost, 6),
    }


def fetch_missing(
    trace_ids: Iterable[str],
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, dict[str, Any]], int]:
    """아직 캐시에 없는 트레이스만 조회해 채운다. `(전체 캐시, 새로 채운 수)`.

    트레이스 하나당 API 호출 한 번이라 목록이 길면 그만큼 걸린다. 호출부가 조회 대상 수를
    제한해서 넘긴다.
    """
    rollup = load_rollup()
    todo = [str(t) for t in trace_ids if t and str(t) not in rollup]
    if not todo:
        return rollup, 0

    for index, trace_id in enumerate(todo, start=1):
        rollup[trace_id] = fetch_trace(trace_id)
        if on_progress is not None:
            on_progress(index, len(todo))

    store.save_json(generation_rollup_file(), rollup)
    return rollup, len(todo)
