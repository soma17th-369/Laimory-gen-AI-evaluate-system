"""항목 점수 → 총점 계산과 채점 결과 저장 포맷.

문서가 요구하는 두 불변식을 지키는지 본다: 항목마다 점수·이유가 있어야 하고, 항목별 점수의
합이 총점과 같아야 한다(평가 입력이 없는 항목은 배점을 비례 배분).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pydantic

from app.analysis import evaluation_record, stage_schema, stages
from app.storage import store


def _card(stage_key: str, *, scores: dict[str, int] | None = None, skipped: set[str] | None = None):
    spec = stages.get(stage_key)
    model = stage_schema.scorecard_model(stage_key)
    return model.model_validate(
        {
            "items": {
                item.key: {
                    "score": (scores or {}).get(item.key, item.points),
                    "applied": item.key not in (skipped or set()),
                    "reason": "확인함",
                }
                for item in spec.items
            },
            "deductions": [],
            "alerts": [],
            "summary": "요약",
        }
    )


class ScorecardModelTests(unittest.TestCase):
    def test_model_has_one_field_per_rubric_item(self) -> None:
        for spec in stages.STAGES:
            model = stage_schema.items_model(spec.key)
            with self.subTest(stage=spec.key):
                self.assertEqual(set(model.model_fields), {item.key for item in spec.items})

    def test_missing_item_is_rejected(self) -> None:
        model = stage_schema.scorecard_model("question")
        payload = {
            "items": {"event_grounding": {"score": 1, "applied": True, "reason": "r"}},
            "deductions": [],
            "alerts": [],
            "summary": "s",
        }

        with self.assertRaises(pydantic.ValidationError):
            model.model_validate(payload)

    def test_empty_reason_is_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            stage_schema.ItemScore(score=5, applied=True, reason="   ")


class TallyTests(unittest.TestCase):
    def test_full_marks_is_one_hundred(self) -> None:
        spec = stages.get("timeline")

        score = stage_schema.tally(spec, _card("timeline"))

        self.assertEqual(score.total, 100.0)
        self.assertEqual(len(score.items), len(spec.items))

    def test_item_scores_add_up_to_the_total(self) -> None:
        spec = stages.get("question")

        score = stage_schema.tally(spec, _card("question", scores={"reflection": 15, "expression": 10}))

        expected = round((20 + 15 + 10 + 20 + 10) / 100 * 100, 1)
        self.assertEqual(score.total, expected)

    def test_unevaluable_item_redistributes_its_points(self) -> None:
        """평가할 입력이 없는 항목은 감점하지 않고 배점을 나머지에 비례 배분한다(문서 규칙)."""
        spec = stages.get("event-photo")

        score = stage_schema.tally(spec, _card("event-photo", skipped={"cluster_merge"}))

        self.assertEqual(score.total, 100.0)
        self.assertEqual(score.redistributed, ("cluster_merge",))
        skipped_item = next(item for item in score.items if item.key == "cluster_merge")
        self.assertFalse(skipped_item.applied)
        self.assertEqual(skipped_item.applied_points, 0.0)

    def test_score_above_the_item_maximum_is_clamped(self) -> None:
        spec = stages.get("question")

        score = stage_schema.tally(spec, _card("question", scores={"uniqueness": 99}))

        self.assertEqual(score.total, 100.0)

    def test_all_items_unevaluable_means_no_score(self) -> None:
        spec = stages.get("event-calendar")

        score = stage_schema.tally(
            spec, _card("event-calendar", skipped={item.key for item in spec.items})
        )

        self.assertIsNone(score.total)
        self.assertFalse(score.evaluated)

    def test_skipped_stage_is_not_zero(self) -> None:
        score = stage_schema.skipped(stages.get("event-photo"), "입력이 0건입니다.")

        self.assertIsNone(score.total)
        self.assertIn("0건", score.skip_reason)


class CompositeTests(unittest.TestCase):
    def test_composite_is_the_mean_of_evaluated_targets(self) -> None:
        scores = [
            stage_schema.tally(stages.get("question"), _card("question", scores={"reflection": 0})),
            stage_schema.tally(stages.get("timeline"), _card("timeline")),
            stage_schema.skipped(stages.get("event-calendar"), "입력이 0건입니다."),
        ]

        composite = stage_schema.composite(scores)

        self.assertEqual(composite["evaluatedCount"], 2)
        self.assertEqual(composite["score"], round((70.0 + 100.0) / 2, 1))
        self.assertIn("event-calendar", composite["skipped"])

    def test_nothing_evaluated_has_no_composite(self) -> None:
        composite = stage_schema.composite([stage_schema.skipped(stages.get("repair"), "반복 없음")])

        self.assertIsNone(composite["score"])


class EvaluationRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [
            mock.patch.object(evaluation_record, "evaluations_dir", lambda: root),
            mock.patch.object(evaluation_record, "evaluation_file", lambda task_id: root / f"{task_id}.json"),
            mock.patch.object(evaluation_record, "evaluation_history_dir", lambda: root / "history"),
            mock.patch.object(
                evaluation_record,
                "evaluation_history_file",
                lambda task_id: root / "history" / f"{task_id}.jsonl",
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _save(self, stage_key: str, **kwargs):
        return evaluation_record.save_stages(
            task_id="task-1",
            trace_id="trace-1",
            env="dev",
            trace_name="generate-timeline",
            date="2026-09-04",
            results={stage_key: stage_schema.tally(stages.get(stage_key), _card(stage_key, **kwargs))},
            rubric_refs={stage_key: {"name": f"judge-stage-{stage_key}", "version": 1}},
            evidence_summaries={stage_key: {"summary": {"events": 3}, "sections": ["실행 정보"]}},
        )

    def test_stages_accumulate_and_composite_follows(self) -> None:
        self._save("question", scores={"reflection": 0})
        record = self._save("timeline")

        self.assertEqual(set(record["stages"]), {"question", "timeline"})
        self.assertEqual(record["composite"]["score"], 85.0)
        self.assertEqual(record["composite"]["evaluatedCount"], 2)

    def test_rescoring_one_stage_keeps_the_others(self) -> None:
        self._save("timeline")
        self._save("question")
        record = self._save("timeline", scores={"day_flow": 0})

        self.assertEqual(record["stages"]["question"]["scorecard"]["total"], 100.0)
        self.assertEqual(record["stages"]["timeline"]["scorecard"]["total"], 85.0)

    def test_legacy_record_is_read_only_and_kept(self) -> None:
        legacy = {"taskId": "task-1", "scorecard": {"overall": {"score": 7}}}

        self.assertTrue(evaluation_record.is_legacy(legacy))
        self.assertEqual(evaluation_record.composite_score(legacy), 70.0)

        evaluation_record.save_stages(
            task_id="task-1",
            trace_id="trace-1",
            env="dev",
            trace_name="generate-timeline",
            date=None,
            results={},
            rubric_refs={},
            evidence_summaries={},
        )
        stored = evaluation_record.load("task-1")
        self.assertFalse(evaluation_record.is_legacy(stored))

    def test_broken_record_is_not_overwritten(self) -> None:
        """다른 단계의 점수가 든 파일을 빈 레코드로 읽어 덮어쓰면 안 된다."""
        path = evaluation_record.evaluation_file("task-1")
        path.write_text("{ 끊긴", encoding="utf-8")

        with self.assertRaises(store.CorruptJson):
            self._save("question")

        self.assertEqual(path.read_text(encoding="utf-8"), "{ 끊긴")

    def test_every_run_is_appended_to_the_history(self) -> None:
        """같은 단계를 다시 채점해도 이전 기록은 지워지지 않는다."""
        self._save("question")
        self._save("question", scores={"reflection": 0})

        history = evaluation_record.load_history("task-1")

        self.assertEqual(len(history), 2)
        self.assertEqual([run["stageKey"] for run in history], ["question", "question"])
        self.assertEqual(sorted(run["total"] for run in history), [70.0, 100.0])
        self.assertNotEqual(history[0]["runId"], history[1]["runId"])

    def test_stages_scored_together_share_one_run_id(self) -> None:
        evaluation_record.save_stages(
            task_id="task-1",
            trace_id="trace-1",
            env="dev",
            trace_name="generate-timeline",
            date=None,
            results={
                key: stage_schema.tally(stages.get(key), _card(key))
                for key in ("question", "timeline")
            },
            rubric_refs={},
            evidence_summaries={},
        )

        history = evaluation_record.load_history("task-1")

        self.assertEqual(len({run["runId"] for run in history}), 1)
        self.assertEqual({run["stageKey"] for run in history}, {"question", "timeline"})

    def test_history_is_newest_first_across_tasks(self) -> None:
        self._save("question")
        history = evaluation_record.load_history()

        self.assertTrue(history)
        self.assertEqual(history, sorted(history, key=lambda run: run["judgedAt"], reverse=True))

    def test_item_reasons_survive_a_round_trip(self) -> None:
        record = self._save("question")

        scores = evaluation_record.to_stage_scores(record)

        self.assertEqual(len(scores), 1)
        self.assertTrue(all(item.reason for item in scores[0].items))


if __name__ == "__main__":
    unittest.main()
