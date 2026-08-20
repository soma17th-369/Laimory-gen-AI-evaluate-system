from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.collect import generations
from app.improve import compare, records
from app.storage import store

_APPLIED = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _row(minutes: int, *, name: str = "generate-timeline", task_id: str | None = None,
         cost: float = 1.0, latency: float = 2.0, trace_id: str | None = None) -> dict:
    """_APPLIED 기준 상대 시각의 트레이스 행. minutes 가 음수면 반영 전."""
    stamp = _APPLIED + timedelta(minutes=minutes)
    return {
        "id": trace_id or f"t{minutes:+05d}",
        "taskId": task_id,
        "name": name,
        "timestamp": str(stamp),
        "user_id": None,
        "latency": latency,
        "total_cost": cost,
    }


def _evaluation(task_id: str, overall: int, *, grounding: int | None = None) -> dict:
    scores = {"grounding": {"score": grounding}} if grounding is not None else {}
    return {"taskId": task_id, "scorecard": {"overall": {"score": overall}, "scores": scores}}


class ImprovementRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [
            mock.patch.object(records, "improvements_dir", lambda: root),
            mock.patch.object(records, "improvement_file", lambda slug: root / f"{slug}.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)
        self.root = root

    def _write(self, slug: str, data: dict) -> None:
        store.save_json(self.root / f"{slug}.json", data)

    def test_legacy_record_without_status_is_read_as_draft(self) -> None:
        self._write("old", {"slug": "old", "plan": "…"})

        record = records.load("old")

        self.assertEqual(record["status"], records.STATUS_DRAFT)
        self.assertIsNone(record["appliedAt"])
        self.assertTrue(record["createdAt"])  # 파일 mtime 으로 채운다
        self.assertEqual(record["taskIds"], [])

    def test_marking_applied_stores_the_given_time(self) -> None:
        self._write("a", {"slug": "a", "plan": "…"})

        saved = records.save_status(
            "a", status=records.STATUS_APPLIED, applied_at="2026-08-10T00:00:00+00:00", note="프롬프트 수정"
        )

        self.assertEqual(saved["appliedAt"], "2026-08-10T00:00:00+00:00")
        self.assertEqual(saved["note"], "프롬프트 수정")
        self.assertEqual(records.load("a")["status"], records.STATUS_APPLIED)

    def test_dropping_clears_the_applied_time(self) -> None:
        self._write("a", {"slug": "a", "plan": "…"})
        records.save_status("a", status=records.STATUS_APPLIED, applied_at="2026-08-10T00:00:00+00:00", note="")

        saved = records.save_status("a", status=records.STATUS_DROPPED, applied_at=None, note="")

        self.assertIsNone(saved["appliedAt"])
        self.assertNotIn(saved, records.applied())

    def test_only_applied_records_are_comparison_targets_in_time_order(self) -> None:
        self._write("late", {"slug": "late", "status": "applied", "appliedAt": "2026-08-15T00:00:00+00:00"})
        self._write("early", {"slug": "early", "status": "applied", "appliedAt": "2026-08-10T00:00:00+00:00"})
        self._write("draft", {"slug": "draft", "status": "draft"})
        self._write("broken", {"slug": "broken", "status": "applied"})  # 반영 시기 없음

        self.assertEqual([r["slug"] for r in records.applied()], ["early", "late"])

    def test_saving_status_keeps_the_plan_body(self) -> None:
        self._write("a", {"slug": "a", "plan": "본문", "taskIds": ["t1"]})

        saved = records.save_status("a", status=records.STATUS_APPLIED, applied_at=None, note="")

        self.assertEqual(saved["plan"], "본문")
        self.assertEqual(saved["taskIds"], ["t1"])
        self.assertIsNotNone(saved["appliedAt"])  # 시각을 안 주면 지금으로 채운다


class SegmentTests(unittest.TestCase):
    def test_each_improvement_owns_the_window_until_the_next_one(self) -> None:
        applied = [
            {"slug": "first", "appliedAt": "2026-08-10T00:00:00+00:00"},
            {"slug": "second", "appliedAt": "2026-08-15T00:00:00+00:00"},
        ]

        segments = compare.segments(applied)

        self.assertEqual([s.slug for s in segments], ["first", "second"])
        self.assertEqual(segments[0].end, segments[1].start)
        self.assertIsNone(segments[1].end)  # 마지막은 현재까지
        self.assertIsNone(segments[0].previous_start)  # 첫 개선책은 '반영 전 전체' 와 비교
        self.assertEqual(segments[1].previous_start, segments[0].start)

    def test_records_without_applied_time_are_skipped(self) -> None:
        self.assertEqual(compare.segments([{"slug": "x"}, {"slug": "y", "appliedAt": "없음"}]), [])

    def test_window_includes_the_start_and_excludes_the_end(self) -> None:
        rows = [_row(-1), _row(0), _row(1)]

        picked = compare.rows_between(rows, _APPLIED, _APPLIED + timedelta(minutes=1))

        self.assertEqual([r["id"] for r in picked], ["t+0000"])


class AggregateTests(unittest.TestCase):
    def test_score_counts_each_task_once_even_with_several_traces(self) -> None:
        rows = [_row(1, task_id="task-1"), _row(2, task_id="task-1"), _row(3, task_id="task-2")]
        evaluations = {"task-1": _evaluation("task-1", 4), "task-2": _evaluation("task-2", 8)}

        result = compare.aggregate(rows, evaluations=evaluations, rollup={})

        self.assertEqual(result.traces, 3)
        self.assertEqual(result.score_n, 2)
        self.assertEqual(result.score_avg, 6.0)

    def test_models_and_tokens_come_from_the_rollup_only(self) -> None:
        rows = [_row(1, trace_id="a"), _row(2, trace_id="b")]
        rollup = {"a": {"models": ["gpt-5.4-mini"], "totalTokens": 1000}}

        result = compare.aggregate(rows, evaluations={}, rollup=rollup)

        self.assertEqual(result.models, {"gpt-5.4-mini": 1})
        self.assertEqual(result.tokens_avg, 1000)
        self.assertEqual(result.tokens_n, 1)  # 조회하지 않은 트레이스는 표본에 넣지 않는다

    def test_empty_window_reports_no_averages(self) -> None:
        result = compare.aggregate([], evaluations={}, rollup={})

        self.assertEqual(result.traces, 0)
        self.assertIsNone(result.cost_avg)
        self.assertIsNone(result.score_avg)
        self.assertEqual(result.cost_sum, 0.0)


class DeltaTests(unittest.TestCase):
    def _deltas(self, before_rows, after_rows, evaluations=None) -> dict[str, compare.MetricDelta]:
        evaluations = evaluations or {}
        before = compare.aggregate(before_rows, evaluations=evaluations, rollup={})
        after = compare.aggregate(after_rows, evaluations=evaluations, rollup={})
        return {d.key: d for d in compare.deltas(before, after)}

    def test_cheaper_after_counts_as_improved(self) -> None:
        deltas = self._deltas([_row(-1, cost=2.0)], [_row(1, cost=1.0)])

        self.assertEqual(deltas["cost_avg"].diff, -1.0)
        self.assertEqual(deltas["cost_avg"].ratio, -0.5)
        self.assertIs(deltas["cost_avg"].improved, True)

    def test_lower_score_after_counts_as_worse(self) -> None:
        evaluations = {"before": _evaluation("before", 8), "after": _evaluation("after", 5)}
        deltas = self._deltas([_row(-1, task_id="before")], [_row(1, task_id="after")], evaluations)

        self.assertIs(deltas["score"].improved, False)
        self.assertEqual(deltas["score"].n_after, 1)

    def test_missing_samples_leave_the_change_undecided(self) -> None:
        deltas = self._deltas([_row(-1)], [_row(1)])

        self.assertIsNone(deltas["score"].diff)
        self.assertIsNone(deltas["score"].improved)
        self.assertIsNone(deltas["tokens_avg"].diff)

    def test_trace_count_is_neutral(self) -> None:
        deltas = self._deltas([_row(-1)], [_row(1), _row(2)])

        self.assertEqual(deltas["traces"].diff, 1)
        self.assertIsNone(deltas["traces"].improved)


class ResultRowTests(unittest.TestCase):
    def test_rows_are_newest_first_and_carry_model_and_score(self) -> None:
        rows = [_row(1, trace_id="a", task_id="task-1"), _row(5, trace_id="b")]
        rollup = {"b": {"models": ["gpt-5.4-mini"], "totalTokens": 700}}

        listed = compare.result_rows(
            rows, evaluations={"task-1": _evaluation("task-1", 7)}, rollup=rollup
        )

        self.assertEqual([r["traceId"] for r in listed], ["b", "a"])
        self.assertEqual(listed[0]["모델"], "gpt-5.4-mini")
        self.assertEqual(listed[0]["토큰"], 700)
        self.assertIsNone(listed[1]["모델"])
        self.assertEqual(listed[1]["종합점수"], 7)

    def test_limit_keeps_the_newest_rows(self) -> None:
        rows = [_row(i, trace_id=f"t{i}") for i in range(1, 6)]

        listed = compare.result_rows(rows, evaluations={}, rollup={}, limit=2)

        self.assertEqual([r["traceId"] for r in listed], ["t5", "t4"])


class GenerationRollupTests(unittest.TestCase):
    def _observation(self, **fields) -> SimpleNamespace:
        base = {
            "model": None,
            "provided_model_name": None,
            "model_id": "4bf01a9f-663f-4302-a05c-b2b42c5348e3",  # 내부 UUID — 화면에 쓰면 안 된다
            "usage_details": None,
            "total_cost": None,
        }
        base.update(fields)
        return SimpleNamespace(**base)

    def _fetch(self, observations: list[SimpleNamespace]) -> dict:
        response = SimpleNamespace(data=observations, meta=SimpleNamespace(cursor=None))
        with mock.patch.object(generations, "list_generations", return_value=response):
            return generations.fetch_trace("trace-1")

    def test_readable_model_name_is_used_not_the_internal_uuid(self) -> None:
        result = self._fetch([self._observation(model="gpt-5.4-mini")])

        self.assertEqual(result["models"], ["gpt-5.4-mini"])

    def test_observation_without_a_readable_name_contributes_no_model(self) -> None:
        result = self._fetch([self._observation()])

        self.assertEqual(result["models"], [])
        self.assertEqual(result["generations"], 1)

    def test_tokens_and_cost_are_summed_across_generations(self) -> None:
        result = self._fetch(
            [
                self._observation(
                    model="gpt-5.4-mini",
                    usage_details={"input": 100, "output": 20, "total": 120},
                    total_cost=0.5,
                ),
                self._observation(
                    model="gpt-5.4-mini",
                    usage_details={"input": 10, "output": 5},  # total 없음 → input+output
                    total_cost=0.25,
                ),
            ]
        )

        self.assertEqual(result["models"], ["gpt-5.4-mini"])  # 같은 모델은 한 번만
        self.assertEqual((result["inputTokens"], result["outputTokens"]), (110, 25))
        self.assertEqual(result["totalTokens"], 135)
        self.assertEqual(result["cost"], 0.75)


class NameBreakdownTests(unittest.TestCase):
    def test_breakdown_reports_both_sides_per_trace_name(self) -> None:
        before = [_row(-1, name="call-llm", cost=1.0), _row(-2, name="main-agent", cost=3.0)]
        after = [_row(1, name="call-llm", cost=0.5)]

        table = {entry["이름"]: entry for entry in compare.name_breakdown(before, after)}

        self.assertEqual(table["call-llm"]["이전 평균비용"], 1.0)
        self.assertEqual(table["call-llm"]["이후 평균비용"], 0.5)
        self.assertEqual(table["main-agent"]["이후 건수"], 0)
        self.assertIsNone(table["main-agent"]["이후 평균비용"])


if __name__ == "__main__":
    unittest.main()
