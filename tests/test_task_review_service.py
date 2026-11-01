"""채점 흐름 서비스 — 화면 없이도 같은 결과가 저장되는지 본다."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.analysis import calibration, evaluation_record, evidence, stage_judge, stages
from app.analysis.evidence import EvidenceSection, StageEvidence
from app.analysis.providers import CodexTimeout
from app.config import Settings
from app.storage import store
from app.storage.paths import task_trace_file
from app.tasks import review


def _card(spec, result_model):
    items = {
        key: {
            f"c{index:02}": {"total": 1, "passed": 1, "failedRefs": [], "reason": "확인함"}
            for index in range(1, len(texts) + 1)
        }
        for key, texts in calibration.definitions(spec).items()
    }
    return result_model.model_validate(
        {"items": items, "deductions": [], "alerts": [], "summary": "요약"}
    )


class _Provider:
    """단계별로 만점을 주고, `failing` 에 든 단계는 시간 초과로 실패한다."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()

    def evaluate(self, *, system_prompt, user_prompt, result_model):
        spec = next(item for item in stages.STAGES if result_model.__name__.startswith(f"{item.key}_"))
        if spec.key in self.failing:
            raise CodexTimeout("시간 초과")
        return _card(spec, result_model)


def _evidence(_trace_json: dict, stage_key: str) -> StageEvidence:
    spec = stages.get(stage_key)
    section = EvidenceSection("실행 정보", "설명", {"events": 1})
    return StageEvidence(spec, True, None, {"events": 1}, (section,))


class JudgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        settings = Settings(_env_file=None, data_dir=self._tmp.name)
        patcher = mock.patch("app.storage.paths.get_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(evidence, "build", _evidence)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _judge(self, provider: _Provider, **kwargs) -> review.JudgeOutcome:
        trace_json = {
            "task": {"traceName": "generate-timeline"},
            "source": {"date": "2026-09-04"},
            "process": {"steps": [], "generations": [], "blobs": {}},
        }
        with mock.patch.object(stage_judge, "get_llm_provider", return_value=provider):
            return review.judge(
                trace_json=trace_json,
                stage_keys=["timeline", "repair"],
                task_id="task-1",
                trace_id="trace-1",
                env="dev",
                **kwargs,
            )

    def test_results_and_the_trace_are_saved(self) -> None:
        outcome = self._judge(_Provider(), trace_meta={"cost": 0.5})

        stored = evaluation_record.load("task-1")
        self.assertEqual(set(stored["stages"]), {"timeline", "repair"})
        self.assertEqual(stored["composite"]["evaluatedCount"], 2)
        self.assertEqual(stored["env"], "dev")
        self.assertEqual(stored["traceName"], "generate-timeline")
        self.assertEqual(outcome.record["composite"], stored["composite"])
        self.assertEqual(outcome.failures, {})
        self.assertTrue(task_trace_file("task-1").exists())

    def test_stages_of_one_run_share_a_run_id_in_the_history(self) -> None:
        self._judge(_Provider(), trace_meta={"cost": 0.5})

        history = evaluation_record.load_history("task-1")

        self.assertEqual({run["stageKey"] for run in history}, {"timeline", "repair"})
        self.assertEqual(len({run["runId"] for run in history}), 1)
        self.assertEqual({run["traceCost"] for run in history}, {0.5})

    def test_rubric_version_is_recorded(self) -> None:
        self._judge(_Provider())

        reference = evaluation_record.load("task-1")["stages"]["timeline"]["rubricRef"]

        self.assertEqual(reference, {"name": "judge-stage-timeline", "version": 1})

    def test_failed_stage_is_reported_and_the_rest_is_saved(self) -> None:
        seen: list[tuple[str, bool]] = []

        outcome = self._judge(
            _Provider({"repair"}),
            on_stage=lambda key, error: seen.append((key, error is not None)),
        )

        self.assertIsInstance(outcome.failures["repair"], CodexTimeout)
        self.assertEqual(set(evaluation_record.load("task-1")["stages"]), {"timeline"})
        self.assertEqual(sorted(seen), [("repair", True), ("timeline", False)])

    def test_scored_index_finds_saved_results(self) -> None:
        self._judge(_Provider())

        self.assertEqual(set(review.scored_index()), {"task-1"})

    def test_saved_trace_keeps_the_input_used_for_scoring(self) -> None:
        self._judge(_Provider())

        self.assertEqual(store.load_json(task_trace_file("task-1"))["source"]["date"], "2026-09-04")


class ImportTests(unittest.TestCase):
    def test_service_does_not_need_streamlit(self) -> None:
        """MCP 서버가 쓰는 계층이다. 화면 패키지를 끌고 오면 안 된다."""
        code = "import sys, app.tasks.review; print('streamlit' in sys.modules)"

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
