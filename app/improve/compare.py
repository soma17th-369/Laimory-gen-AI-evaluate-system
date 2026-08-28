"""개선책 **반영 시기 전후**의 지표를 비교한다.

비교의 시간축은 **트레이스가 생긴 시각**(`collection.json` 행의 `timestamp`)이다. 평가 파일에는
자체 시각이 없으므로 `taskId` 로 트레이스 행에 붙인다. 그래서 이 모듈은 항상 트레이스 행을
순회하고, 평가·토큰·모델은 거기에 붙이는 부가 정보로 다룬다.

구간은 개선책이 나눈다. 반영 시각이 이른 순으로 늘어놓았을 때 개선책 하나가 맡는 구간은
`[반영 시각, 다음 개선책 반영 시각)` 이고, 마지막 개선책은 현재까지다. 비교 대상(`이전 구간`)은
직전 개선책의 구간이며, 첫 개선책은 반영 전 전체가 된다.

표본 수(`n`)를 값과 항상 함께 돌려준다. 점수·토큰은 채점·상세 조회를 한 트레이스에만 있어서
표본이 적을 수 있고, n 없이 평균만 보면 오해를 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from app import environments
from app.analysis.schema import CRITERION_KEYS, CRITERION_LABELS
from app.collect.sync import parse_timestamp

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Segment:
    """개선책 하나가 맡는 구간."""

    record: dict[str, Any]
    start: datetime
    end: datetime | None
    """다음 개선책 반영 시각. 마지막 개선책이면 None(현재까지)."""

    previous_start: datetime | None
    """비교 대상 구간의 시작. None 이면 '반영 전 전체'."""

    @property
    def slug(self) -> str:
        return str(self.record.get("slug") or "unnamed")

    @property
    def previous_label(self) -> str:
        return "직전 구간" if self.previous_start is not None else "반영 전 전체"


def segments(applied_records: Sequence[dict[str, Any]]) -> list[Segment]:
    """반영 시각 오름차순 레코드를 구간으로 자른다. 반영 시각이 없는 레코드는 건너뛴다."""
    parsed = []
    for record in applied_records:
        start = parse_timestamp(record.get("appliedAt"))
        if start is not None:
            parsed.append((start, record))
    parsed.sort(key=lambda item: item[0])

    out: list[Segment] = []
    for index, (start, record) in enumerate(parsed):
        end = parsed[index + 1][0] if index + 1 < len(parsed) else None
        previous_start = parsed[index - 1][0] if index > 0 else None
        out.append(Segment(record=record, start=start, end=end, previous_start=previous_start))
    return out


def rows_between(
    rows: Sequence[dict[str, Any]],
    start: datetime | None,
    end: datetime | None,
) -> list[dict[str, Any]]:
    """`start <= timestamp < end` 인 행. 경계는 시작 포함·끝 제외."""
    picked = []
    for row in rows:
        stamp = parse_timestamp(row.get("timestamp"))
        if stamp is None:
            continue
        if start is not None and stamp < start:
            continue
        if end is not None and stamp >= end:
            continue
        picked.append(row)
    return picked


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class Aggregate:
    """한 구간의 집계."""

    traces: int = 0
    latency_avg: float | None = None
    cost_avg: float | None = None
    cost_sum: float = 0.0
    tokens_avg: float | None = None
    tokens_n: int = 0
    score_avg: float | None = None
    score_n: int = 0
    criterion_avg: dict[str, float] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    """모델명 → 그 모델을 쓴 트레이스 수(상세 조회한 트레이스 한정)."""


def aggregate(
    rows: Sequence[dict[str, Any]],
    *,
    evaluations: dict[str, dict[str, Any]],
    rollup: dict[str, dict[str, Any]],
) -> Aggregate:
    """구간 행을 집계한다.

    `evaluations` 는 taskId → 평가 dict, `rollup` 은 traceId → 모델·토큰 dict.
    한 taskId 에 트레이스가 여럿이어도 **점수는 task 당 한 번만** 센다.
    """
    latencies: list[float] = []
    costs: list[float] = []
    tokens: list[float] = []
    models: dict[str, int] = {}
    scored_tasks: dict[str, dict[str, Any]] = {}

    for row in rows:
        latency = _number(row.get("latency"))
        if latency is not None:
            latencies.append(latency)
        cost = _number(row.get("total_cost"))
        if cost is not None:
            costs.append(cost)

        meta = rollup.get(str(row.get("id")))
        if meta:
            total = _number(meta.get("totalTokens"))
            if total is not None:
                tokens.append(total)
            for name in meta.get("models") or []:
                models[str(name)] = models.get(str(name), 0) + 1

        task_id = row.get("taskId")
        if task_id and str(task_id) in evaluations and str(task_id) not in scored_tasks:
            scored_tasks[str(task_id)] = evaluations[str(task_id)]

    overalls: list[float] = []
    per_criterion: dict[str, list[float]] = {key: [] for key in CRITERION_KEYS}
    for evaluation in scored_tasks.values():
        card = evaluation.get("scorecard") or {}
        overall = _number((card.get("overall") or {}).get("score"))
        if overall is not None:
            overalls.append(overall)
        scores = card.get("scores") or {}
        for key in CRITERION_KEYS:
            value = _number((scores.get(key) or {}).get("score"))
            if value is not None:
                per_criterion[key].append(value)

    criterion_avg: dict[str, float] = {}
    for key, values in per_criterion.items():
        mean = _mean(values)
        if mean is not None:
            criterion_avg[key] = mean

    return Aggregate(
        traces=len(rows),
        latency_avg=_mean(latencies),
        cost_avg=_mean(costs),
        cost_sum=sum(costs),
        tokens_avg=_mean(tokens),
        tokens_n=len(tokens),
        score_avg=_mean(overalls),
        score_n=len(overalls),
        criterion_avg=criterion_avg,
        models=models,
    )


@dataclass(frozen=True)
class MetricDelta:
    """지표 하나의 전후 값. `better` 는 좋아지는 방향(None 이면 중립)."""

    key: str
    label: str
    before: float | None
    after: float | None
    n_before: int
    n_after: int
    better: str | None = None
    unit: str = ""

    @property
    def diff(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before

    @property
    def ratio(self) -> float | None:
        """변화율. 이전 값이 없거나 0 이면 None."""
        if self.before is None or self.before == 0 or self.after is None:
            return None
        return (self.after - self.before) / abs(self.before)

    @property
    def improved(self) -> bool | None:
        """좋아졌으면 True, 나빠졌으면 False. 중립이거나 변화가 없으면 None."""
        diff = self.diff
        if diff is None or self.better is None or diff == 0:
            return None
        return diff > 0 if self.better == "up" else diff < 0


def deltas(before: Aggregate, after: Aggregate) -> list[MetricDelta]:
    """구간 전후 핵심 지표. 목록 순서가 곧 화면 순서다."""
    return [
        MetricDelta("traces", "트레이스 수", before.traces, after.traces, before.traces, after.traces),
        MetricDelta(
            "score", "종합 점수", before.score_avg, after.score_avg,
            before.score_n, after.score_n, better="up", unit="/10",
        ),
        MetricDelta(
            "cost_avg", "평균 비용", before.cost_avg, after.cost_avg,
            before.traces, after.traces, better="down",
        ),
        MetricDelta(
            "tokens_avg", "평균 토큰", before.tokens_avg, after.tokens_avg,
            before.tokens_n, after.tokens_n, better="down",
        ),
        MetricDelta(
            "latency_avg", "평균 latency", before.latency_avg, after.latency_avg,
            before.traces, after.traces, better="down", unit="s",
        ),
        MetricDelta("cost_sum", "총 비용", before.cost_sum, after.cost_sum, before.traces, after.traces),
    ]


def criterion_deltas(before: Aggregate, after: Aggregate) -> list[MetricDelta]:
    """채점 기준별 점수 전후(둘 중 한쪽이라도 값이 있는 기준만)."""
    out = []
    for key in CRITERION_KEYS:
        low, high = before.criterion_avg.get(key), after.criterion_avg.get(key)
        if low is None and high is None:
            continue
        out.append(
            MetricDelta(
                key, CRITERION_LABELS.get(key, key), low, high,
                before.score_n, after.score_n, better="up", unit="/10",
            )
        )
    return out


def result_rows(
    rows: Sequence[dict[str, Any]],
    *,
    evaluations: dict[str, dict[str, Any]],
    rollup: dict[str, dict[str, Any]],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """구간의 결과 목록(최신순). 모델·토큰은 상세 조회한 트레이스만 채워진다."""
    ordered = sorted(
        rows,
        key=lambda row: parse_timestamp(row.get("timestamp")) or _OLDEST,
        reverse=True,
    )
    if limit is not None:
        ordered = ordered[:limit]

    out = []
    for row in ordered:
        meta = rollup.get(str(row.get("id"))) or {}
        task_id = row.get("taskId")
        evaluation = evaluations.get(str(task_id)) if task_id else None
        card = (evaluation or {}).get("scorecard") or {}
        models = meta.get("models") or []
        out.append(
            {
                "시각": row.get("timestamp"),
                "환경": environments.short_label(environments.of(row)),
                "이름": row.get("name"),
                "모델": ", ".join(str(m) for m in models) if models else None,
                "토큰": meta.get("totalTokens"),
                "비용": row.get("total_cost"),
                "latency(s)": row.get("latency"),
                "종합점수": (card.get("overall") or {}).get("score"),
                "taskId": task_id,
                "traceId": row.get("id"),
            }
        )
    return out


def name_breakdown(
    before_rows: Sequence[dict[str, Any]],
    after_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """트레이스 이름별 건수·평균 비용 전후.

    단계마다 비용 규모가 달라서, 전체 평균만 보면 구성비 변화가 개선 효과처럼 보인다.
    """

    def by_name(rows: Sequence[dict[str, Any]]) -> dict[str, list[float]]:
        table: dict[str, list[float]] = {}
        for row in rows:
            name = str(row.get("name") or "(이름없음)")
            table.setdefault(name, [])
            cost = _number(row.get("total_cost"))
            if cost is not None:
                table[name].append(cost)
        return table

    low, high = by_name(before_rows), by_name(after_rows)
    out = []
    for name in sorted(set(low) | set(high)):
        out.append(
            {
                "이름": name,
                "이전 건수": len(low.get(name, [])),
                "이후 건수": len(high.get(name, [])),
                "이전 평균비용": _mean(low.get(name, [])),
                "이후 평균비용": _mean(high.get(name, [])),
            }
        )
    return out
