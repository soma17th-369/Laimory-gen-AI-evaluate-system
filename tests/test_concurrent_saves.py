"""화면과 MCP 서버는 별도 프로세스다. 동시에 저장해도 기록이 사라지면 안 된다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import environments
from app.analysis import evaluation_record, stages
from app.collect import sync as collect
from app.config import Settings
from app.prompts import registry
from app.storage import store

_REPO = Path(__file__).resolve().parents[1]

_SAVE_ONE_STAGE = """
import sys
from app.analysis import evaluation_record, stage_schema, stages

key = sys.argv[1]
for turn in range(15):
    evaluation_record.save_stages(
        task_id="task-1",
        trace_id="trace-1",
        env="dev",
        trace_name="generate-timeline",
        date=None,
        results={key: stage_schema.skipped(stages.get(key), f"사유 {turn}")},
        rubric_refs={},
        evidence_summaries={},
    )
"""


class ConcurrentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        settings = Settings(_env_file=None, data_dir=self._tmp.name)
        patcher = mock.patch("app.storage.paths.get_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)


class EvaluationRecordProcessTests(ConcurrentTestCase):
    def test_processes_saving_different_stages_keep_every_stage(self) -> None:
        keys = [spec.key for spec in stages.STAGES]
        env = dict(os.environ, DATA_DIR=self._tmp.name)
        workers = [
            subprocess.Popen(
                [sys.executable, "-c", _SAVE_ONE_STAGE, key],
                cwd=_REPO,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for key in keys
        ]
        errors = [worker.communicate(timeout=120)[1] for worker in workers]

        self.assertEqual([worker.returncode for worker in workers], [0] * len(keys), errors)
        stored = evaluation_record.load("task-1")
        self.assertEqual(set(stored["stages"]), set(keys))
        history = evaluation_record.load_history("task-1")
        self.assertEqual(len(history), 15 * len(keys))


class RegistryThreadTests(ConcurrentTestCase):
    def _run_all(self, contents: list[str]) -> list[dict]:
        results: list[dict] = []

        def save(content: str) -> None:
            results.append(registry.get_or_create("judge-stage-question", content))

        threads = [threading.Thread(target=save, args=(content,)) for content in contents]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def test_same_content_makes_one_version(self) -> None:
        results = self._run_all(["같은 본문"] * 8)

        self.assertEqual({record["version"] for record in results}, {1})
        self.assertEqual(len(registry.list_versions("judge-stage-question")), 1)

    def test_different_contents_get_different_numbers(self) -> None:
        contents = [f"본문 {index}" for index in range(8)]

        self._run_all(contents)

        versions = registry.list_versions("judge-stage-question")
        self.assertEqual([record["version"] for record in versions], list(range(1, 9)))
        self.assertEqual({record["content"] for record in versions}, set(contents))


class SyncInterleavingTests(ConcurrentTestCase):
    """수집은 호출 한도를 기다리느라 오래 걸린다. 그 사이 다른 프로세스가 저장할 수 있다."""

    def _trace(self, trace_id: str, minute: int) -> SimpleNamespace:
        return SimpleNamespace(
            id=trace_id,
            timestamp=f"2026-08-01T00:{minute:02d}:00+00:00",
            name="main-agent",
            input={"taskId": f"task-{trace_id}"},
            user_id=None,
            latency=1.0,
            total_cost=0.5,
        )

    def _sync_while(self, other_process_saves) -> None:
        def list_traces(**_kwargs):
            other_process_saves()
            return SimpleNamespace(
                data=[self._trace("mine", 1)], meta=SimpleNamespace(total_pages=1)
            )

        with mock.patch.object(collect, "list_traces", list_traces):
            collect.sync(environments.DEV)

    def test_rows_saved_by_another_process_survive(self) -> None:
        def save() -> None:
            store.save_json(collect.collection_file(), [{"id": "theirs", "env": "prod", "timestamp": None}])

        self._sync_while(save)

        self.assertEqual({row["id"] for row in collect.load_rows()}, {"mine", "theirs"})

    def test_cursor_saved_by_another_process_survives(self) -> None:
        theirs = {"backfilled": True, "last_timestamp": "2026-08-01T00:09:00+00:00", "total": 3}

        def save() -> None:
            store.save_json(collect.collection_state_file(), {environments.PROD: theirs})

        self._sync_while(save)

        states = collect.load_states()
        self.assertEqual(states[environments.PROD], theirs)
        self.assertTrue(states[environments.DEV]["backfilled"])

    def test_result_counts_the_merged_rows(self) -> None:
        def save() -> None:
            store.save_json(collect.collection_file(), [{"id": "theirs", "env": "dev", "timestamp": None}])

        with mock.patch.object(
            collect,
            "list_traces",
            lambda **_kwargs: (save(), SimpleNamespace(data=[self._trace("mine", 1)], meta=SimpleNamespace(total_pages=1)))[1],
        ):
            result = collect.sync(environments.DEV)

        self.assertEqual((result.total, result.stored_total), (2, 2))
        self.assertEqual(json.loads(collect.collection_state_file().read_text(encoding="utf-8"))["dev"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
