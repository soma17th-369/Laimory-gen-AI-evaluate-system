from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import environments
from app.collect import sync as collect
from app.storage import store

_START = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _trace(index: int, *, name: str = "main-agent", user_id: str | None = None) -> SimpleNamespace:
    """LangFuse 트레이스 흉내. index 가 클수록 최신."""
    return SimpleNamespace(
        id=f"t{index:03d}",
        timestamp=_START + timedelta(minutes=index),
        name=name,
        input={"taskId": f"task-{index}"},
        user_id=user_id,
        latency=1.0,
        total_cost=0.5,
        observations=None,
    )


class FakeLangfuse:
    """timestamp 오름차순 페이지네이션과 from_timestamp(경계 포함) 필터를 흉내낸다."""

    def __init__(self, traces: list[SimpleNamespace]) -> None:
        self.traces = traces  # 테스트가 나중에 추가·삭제할 수 있게 참조를 유지한다
        self.calls: list[dict] = []

    def list_traces(self, *, page, limit, from_timestamp, order_by, fields, env):
        assert order_by == "timestamp.asc"
        assert "io" in fields and "metrics" in fields  # taskId·latency·total_cost 가 필요하다
        self.calls.append(
            {"page": page, "limit": limit, "from_timestamp": from_timestamp, "env": env}
        )
        items = sorted(self.traces, key=lambda t: t.timestamp)
        if from_timestamp is not None:
            items = [t for t in items if t.timestamp >= from_timestamp]
        total_pages = max(1, -(-len(items) // limit))
        start = (page - 1) * limit
        return SimpleNamespace(
            data=items[start : start + limit],
            meta=SimpleNamespace(page=page, limit=limit, total_items=len(items), total_pages=total_pages),
        )


class CollectionSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [
            mock.patch.object(collect, "collection_file", lambda: root / "collection.json"),
            mock.patch.object(collect, "collection_state_file", lambda: root / "collection.state.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _server(self, traces: list[SimpleNamespace]) -> FakeLangfuse:
        server = FakeLangfuse(traces)
        patch = mock.patch.object(collect, "list_traces", server.list_traces)
        patch.start()
        self.addCleanup(patch.stop)
        return server

    def test_first_sync_downloads_every_page_from_the_beginning(self) -> None:
        self._server([_trace(i) for i in range(1, 6)])

        result = collect.sync(environments.DEV, page_size=2)

        self.assertEqual(result.mode, "backfill")
        self.assertEqual((result.added, result.total, result.pages), (5, 5, 3))
        self.assertTrue(result.completed)
        rows = collect.load_rows()
        self.assertEqual([row["id"] for row in rows], ["t005", "t004", "t003", "t002", "t001"])
        self.assertEqual(rows[0]["taskId"], "task-5")
        self.assertEqual({row["env"] for row in rows}, {environments.DEV})
        self.assertTrue(collect.load_state(environments.DEV)["backfilled"])
        self.assertNotIn("filters", collect.load_state(environments.DEV))

    def test_second_sync_only_downloads_traces_created_after_the_saved_ones(self) -> None:
        traces = [_trace(i) for i in range(1, 6)]
        server = self._server(traces)
        collect.sync(environments.DEV, page_size=2)
        server.calls.clear()
        server.traces.extend([_trace(6), _trace(7)])

        result = collect.sync(environments.DEV, page_size=2)

        self.assertEqual(result.mode, "incremental")
        self.assertEqual((result.added, result.updated, result.total), (2, 0, 7))
        # 커서(마지막 저장 로그 시각)부터 조회하므로 경계 1건 + 신규 2건만 내려받는다.
        self.assertEqual(result.fetched, 3)
        self.assertEqual(server.calls[0]["from_timestamp"], traces[4].timestamp)
        self.assertEqual([row["id"] for row in collect.load_rows()][:2], ["t007", "t006"])

    def test_sync_keeps_rows_that_the_server_no_longer_returns(self) -> None:
        server = self._server([_trace(i) for i in range(1, 4)])
        collect.sync(environments.DEV, page_size=10)
        server.traces.clear()

        result = collect.sync(environments.DEV, page_size=10)

        self.assertEqual(result.added, 0)
        self.assertEqual(len(collect.load_rows()), 3)

    def test_interrupted_backfill_resumes_from_the_last_saved_trace(self) -> None:
        self._server([_trace(i) for i in range(1, 7)])

        first = collect.sync(environments.DEV, page_size=2, max_pages=2)

        self.assertFalse(first.completed)
        self.assertEqual([row["id"] for row in collect.load_rows()], ["t004", "t003", "t002", "t001"])

        second = collect.sync(environments.DEV, page_size=2)

        self.assertEqual(second.mode, "incremental")
        self.assertEqual(second.added, 2)
        self.assertEqual(second.total, 6)
        self.assertTrue(second.completed)

    def test_interrupted_backfill_does_not_skip_the_gap_below_older_snapshot_rows(self) -> None:
        """예전 스냅샷의 최신 행이 남아 있어도 커서는 훑은 구간의 끝까지만 전진해야 한다."""
        newest = _trace(99)
        store.save_json(collect.collection_file(), [collect.row_of(newest, environments.DEV)])
        server = self._server([_trace(i) for i in range(1, 7)] + [newest])

        first = collect.sync(environments.DEV, page_size=2, max_pages=1)

        self.assertFalse(first.completed)
        self.assertEqual(
            collect.load_state(environments.DEV)["last_timestamp"], _trace(2).timestamp.isoformat()
        )

        server.calls.clear()
        collect.sync(environments.DEV, page_size=10)

        # 커서가 t099 로 튀었다면 t003~t006 이 영영 빠진다.
        self.assertEqual(server.calls[0]["from_timestamp"], _trace(2).timestamp)
        self.assertEqual(
            sorted(row["id"] for row in collect.load_rows()),
            ["t001", "t002", "t003", "t004", "t005", "t006", "t099"],
        )

    def test_legacy_timestamp_string_is_parsed(self) -> None:
        parsed = collect.parse_timestamp("2026-08-14 04:30:00.197000+00:00")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNone(collect.parse_timestamp(None))
        self.assertIsNone(collect.parse_timestamp("없는 시각"))


class MultiEnvironmentServer:
    """환경마다 다른 트레이스를 돌려주는 LangFuse 흉내."""

    def __init__(self, by_environment: dict[str, list[SimpleNamespace]]) -> None:
        self.by_environment = by_environment
        self.calls: list[dict] = []

    def list_traces(self, *, page, limit, from_timestamp, order_by, fields, env):
        self.calls.append({"page": page, "from_timestamp": from_timestamp, "env": env})
        items = sorted(self.by_environment.get(env, []), key=lambda t: t.timestamp)
        if from_timestamp is not None:
            items = [t for t in items if t.timestamp >= from_timestamp]
        total_pages = max(1, -(-len(items) // limit))
        start = (page - 1) * limit
        return SimpleNamespace(
            data=items[start : start + limit],
            meta=SimpleNamespace(page=page, limit=limit, total_pages=total_pages),
        )


class MergedEnvironmentTests(unittest.TestCase):
    """개발·운영을 한 목록에 합치되, 커서는 환경마다 따로 간다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [
            mock.patch.object(collect, "collection_file", lambda: root / "collection.json"),
            mock.patch.object(
                collect, "collection_state_file", lambda: root / "collection.state.json"
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _server(self, by_environment: dict[str, list[SimpleNamespace]]) -> MultiEnvironmentServer:
        server = MultiEnvironmentServer(by_environment)
        patch = mock.patch.object(collect, "list_traces", server.list_traces)
        patch.start()
        self.addCleanup(patch.stop)
        return server

    def test_both_environments_land_in_one_time_sorted_list(self) -> None:
        self._server(
            {
                environments.DEV: [_trace(1), _trace(3)],
                environments.PROD: [_trace(2), _trace(4)],
            }
        )

        collect.sync_all([environments.DEV, environments.PROD], page_size=10)

        rows = collect.load_rows()
        self.assertEqual([row["id"] for row in rows], ["t004", "t003", "t002", "t001"])
        self.assertEqual(
            [row["env"] for row in rows],
            [environments.PROD, environments.DEV, environments.PROD, environments.DEV],
        )

    def test_each_environment_keeps_its_own_cursor(self) -> None:
        server = self._server(
            {environments.DEV: [_trace(1), _trace(2)], environments.PROD: [_trace(5)]}
        )

        collect.sync_all([environments.DEV, environments.PROD], page_size=10)
        server.calls.clear()
        collect.sync(environments.PROD, page_size=10)

        # 운영 재조회는 운영 커서(t005)부터. 개발 커서(t002)에 영향받지 않는다.
        self.assertEqual(server.calls[0]["env"], environments.PROD)
        self.assertEqual(server.calls[0]["from_timestamp"], _trace(5).timestamp)
        states = collect.load_states()
        self.assertEqual(states[environments.DEV]["last_timestamp"], _trace(2).timestamp.isoformat())
        self.assertEqual(states[environments.PROD]["last_timestamp"], _trace(5).timestamp.isoformat())

    def test_syncing_one_environment_keeps_the_other_environment_rows(self) -> None:
        self._server({environments.DEV: [_trace(1)], environments.PROD: [_trace(2)]})
        collect.sync_all([environments.DEV, environments.PROD], page_size=10)

        result = collect.sync(environments.PROD, full=True, page_size=10)

        self.assertEqual(result.total, 1)  # 운영 저장 행 수
        self.assertEqual(result.stored_total, 2)  # 전체 저장 행 수
        self.assertEqual(sorted(row["id"] for row in collect.load_rows()), ["t001", "t002"])

    def test_cursor_saved_before_environments_existed_is_read_as_dev(self) -> None:
        store.save_json(
            collect.collection_state_file(),
            {"backfilled": True, "last_timestamp": _trace(3).timestamp.isoformat()},
        )

        self.assertFalse(collect.needs_backfill(collect.load_state(environments.DEV)))
        self.assertTrue(collect.needs_backfill(collect.load_state(environments.PROD)))

    def test_rows_saved_before_environments_existed_count_as_dev(self) -> None:
        store.save_json(collect.collection_file(), [{"id": "old", "timestamp": None}])

        rows = collect.load_rows()

        self.assertEqual(collect.rows_of(rows, environments.DEV), rows)
        self.assertEqual(collect.rows_of(rows, environments.PROD), [])


if __name__ == "__main__":
    unittest.main()
