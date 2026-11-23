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
_WINDOW = timedelta(minutes=2)
_NOW = _START + timedelta(minutes=10)


def _trace(index: int, *, name: str = "main-agent", minute: int | None = None, session: str | None = "") -> SimpleNamespace:
    """LangFuse 트레이스 요약 흉내. index 가 클수록 최신. taskId 는 세션 id 로 온다."""
    return SimpleNamespace(
        id=f"t{index:03d}",
        timestamp=_START + timedelta(minutes=index if minute is None else minute),
        name=name,
        session_id=f"task-{index}" if session == "" else session,
        user_id=None,
        latency=1.0,
        total_cost=0.5,
    )


class FakeLangfuse:
    """v2 관측치처럼 시간 구간 `[from, to)` 로만 고르고, 결과는 최신순으로 준다."""

    def __init__(self, traces: list[SimpleNamespace]) -> None:
        self.traces = traces  # 테스트가 나중에 추가·삭제할 수 있게 참조를 유지한다
        self.calls: list[dict] = []
        self.probes: list[tuple[datetime, datetime]] = []

    def list_traces(self, *, from_timestamp, to_timestamp, env):
        self.calls.append({"from_timestamp": from_timestamp, "to_timestamp": to_timestamp, "env": env})
        picked = [t for t in self.traces if from_timestamp <= t.timestamp < to_timestamp]
        return sorted(picked, key=lambda t: t.timestamp, reverse=True)

    def has_traces(self, *, from_timestamp, to_timestamp, env):
        self.probes.append((from_timestamp, to_timestamp))
        return any(from_timestamp <= t.timestamp < to_timestamp for t in self.traces)


class SyncTestCase(unittest.TestCase):
    """저장 경로를 임시 폴더로, 지금 시각·전체 수집 시작점을 고정한다. 앞당겨 받기는 끈다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [
            mock.patch.object(collect, "collection_file", lambda: root / "collection.json"),
            mock.patch.object(collect, "collection_state_file", lambda: root / "collection.state.json"),
            mock.patch.object(collect, "_now", lambda: _NOW),
            mock.patch.object(collect, "HISTORY_START", _START - timedelta(minutes=40)),
            mock.patch.object(collect, "LOOKBACK", timedelta(0)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _patch_server(self, server) -> None:
        for name in ("list_traces", "has_traces"):
            patch = mock.patch.object(collect, name, getattr(server, name))
            patch.start()
            self.addCleanup(patch.stop)


class CollectionSyncTests(SyncTestCase):
    def _server(self, traces: list[SimpleNamespace]) -> FakeLangfuse:
        server = FakeLangfuse(traces)
        self._patch_server(server)
        return server

    def test_first_sync_downloads_everything_from_the_oldest_trace(self) -> None:
        server = self._server([_trace(i) for i in range(1, 6)])

        result = collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual(result.mode, "backfill")
        # 가장 오래된 트레이스가 든 구간([0분, 2분))부터 지금(10분)까지 다섯 구간.
        self.assertEqual((result.added, result.total, result.pages), (5, 5, 5))
        self.assertTrue(result.completed)
        self.assertEqual(server.calls[0]["from_timestamp"], _START)
        # 앞쪽 빈 구간 스무 개는 하나씩 부르지 않고 이분 탐색으로 건너뛴다.
        self.assertLessEqual(len(server.probes), 6)
        rows = collect.load_rows()
        self.assertEqual([row["id"] for row in rows], ["t005", "t004", "t003", "t002", "t001"])
        self.assertEqual(rows[0]["taskId"], "task-5")
        self.assertEqual({row["env"] for row in rows}, {environments.DEV})
        self.assertTrue(collect.load_state(environments.DEV)["backfilled"])
        self.assertNotIn("filters", collect.load_state(environments.DEV))

    def test_first_sync_with_nothing_on_the_server_saves_an_empty_collection(self) -> None:
        server = self._server([])

        result = collect.sync(environments.DEV, window=_WINDOW)

        self.assertTrue(result.completed)
        self.assertEqual((result.added, result.pages), (0, 0))
        self.assertEqual(server.calls, [])
        self.assertEqual(collect.load_rows(), [])

    def test_second_sync_only_downloads_traces_created_after_the_saved_ones(self) -> None:
        traces = [_trace(i) for i in range(1, 6)]
        server = self._server(traces)
        collect.sync(environments.DEV, window=_WINDOW)
        server.calls.clear()
        server.traces.extend([_trace(6), _trace(7)])

        result = collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual(result.mode, "incremental")
        self.assertEqual((result.added, result.updated, result.total), (2, 0, 7))
        # 커서(마지막 저장 로그 시각)부터 조회하므로 경계 1건 + 신규 2건만 내려받는다.
        self.assertEqual(result.fetched, 3)
        self.assertEqual(server.calls[0]["from_timestamp"], traces[4].timestamp)
        self.assertEqual([row["id"] for row in collect.load_rows()][:2], ["t007", "t006"])

    def test_incremental_sync_looks_back_for_traces_that_finished_late(self) -> None:
        """루트는 트레이스가 끝나야 올라온다. 커서보다 먼저 시작했지만 늦게 끝난 것도 받아야 한다."""
        server = self._server([_trace(i) for i in range(1, 6)])
        collect.sync(environments.DEV, window=_WINDOW)
        del server.traces[4]  # 커서(t005)보다 앞선 행만 남겨 커서가 물러나는지 본다
        server.traces.append(_trace(50, minute=4))

        with mock.patch.object(collect, "LOOKBACK", timedelta(minutes=3)):
            result = collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual(result.added, 1)
        self.assertIn("t050", [row["id"] for row in collect.load_rows()])
        # 앞당겨 받은 구간의 행만 새로 생겼어도 커서는 뒤로 물러나지 않는다.
        self.assertEqual(
            collect.load_state(environments.DEV)["last_timestamp"], _trace(5).timestamp.isoformat()
        )

    def test_reused_trace_id_keeps_the_first_time_and_task_id(self) -> None:
        """대상 서버 테스트가 옛 트레이스 id 를 재사용하면 새 루트가 늦은 시각·세션 없이 온다."""
        server = self._server([_trace(1)])
        collect.sync(environments.DEV, window=_WINDOW)
        server.traces[:] = [_trace(1, minute=7, session=None)]

        collect.sync(environments.DEV, window=_WINDOW)

        (row,) = collect.load_rows()
        self.assertEqual(row["timestamp"], str(_trace(1).timestamp))
        self.assertEqual(row["taskId"], "task-1")
        self.assertEqual(
            collect.load_state(environments.DEV)["last_timestamp"], _trace(1, minute=7).timestamp.isoformat()
        )

    def test_sync_keeps_rows_that_the_server_no_longer_returns(self) -> None:
        server = self._server([_trace(i) for i in range(1, 4)])
        collect.sync(environments.DEV, window=_WINDOW)
        server.traces.clear()

        result = collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual(result.added, 0)
        self.assertEqual(len(collect.load_rows()), 3)

    def test_interrupted_backfill_resumes_from_the_last_saved_trace(self) -> None:
        self._server([_trace(i) for i in range(1, 7)])

        first = collect.sync(environments.DEV, window=_WINDOW, max_pages=2)

        self.assertFalse(first.completed)
        self.assertEqual([row["id"] for row in collect.load_rows()], ["t003", "t002", "t001"])

        second = collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual(second.mode, "incremental")
        self.assertEqual(second.added, 3)
        self.assertEqual(second.total, 6)
        self.assertTrue(second.completed)

    def test_failed_sync_keeps_the_windows_it_already_received(self) -> None:
        """조회가 중간에 실패해도(호출 한도 등) 받은 만큼 저장하고 다음 실행이 이어받는다."""
        server = self._server([_trace(i) for i in range(1, 7)])
        healthy = server.list_traces

        def failing(**kwargs):
            if len(server.calls) == 2:
                raise RuntimeError("rate limited")
            return healthy(**kwargs)

        with mock.patch.object(collect, "list_traces", failing):
            with self.assertRaises(RuntimeError):
                collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual([row["id"] for row in collect.load_rows()], ["t003", "t002", "t001"])
        self.assertEqual(
            collect.load_state(environments.DEV)["last_timestamp"], _trace(3).timestamp.isoformat()
        )

        second = collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual((second.added, second.total), (3, 6))
        self.assertTrue(second.completed)

    def test_long_sync_saves_along_the_way(self) -> None:
        """프로세스가 강제로 끝나면 예외 처리도 돌지 않는다. 그 전에 받은 만큼은 남아 있어야 한다."""
        server = self._server([_trace(i) for i in range(1, 8)])
        healthy = server.list_traces
        seen_at_window_3: list[str] = []

        def watching(**kwargs):
            if len(server.calls) == 2:
                seen_at_window_3.extend(row["id"] for row in collect.load_rows())
            return healthy(**kwargs)

        with (
            mock.patch.object(collect, "list_traces", watching),
            mock.patch.object(collect, "SAVE_EVERY_PAGES", 2),
        ):
            collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual(sorted(seen_at_window_3), ["t001", "t002", "t003"])
        self.assertEqual(len(collect.load_rows()), 7)

    def test_stopped_sync_saves_what_it_received_and_resumes(self) -> None:
        server = self._server([_trace(i) for i in range(1, 6)])
        answers = iter([False, True])

        first = collect.sync(environments.DEV, window=_WINDOW, should_stop=lambda: next(answers))

        self.assertFalse(first.completed)
        self.assertEqual((first.pages, first.total), (1, 1))
        self.assertEqual(len(server.calls), 1)

        second = collect.sync(environments.DEV, window=_WINDOW)

        self.assertEqual((second.mode, second.total), ("incremental", 5))
        self.assertTrue(second.completed)

    def test_broken_collection_stops_the_sync_instead_of_overwriting_it(self) -> None:
        """깨진 파일을 빈 목록으로 읽으면 쌓인 로그가 이번에 받은 행으로 덮어써진다."""
        server = self._server([_trace(1)])
        collect.collection_file().write_text("[ 끊긴", encoding="utf-8")

        with self.assertRaises(store.CorruptJson):
            collect.sync(environments.DEV)

        self.assertEqual(collect.collection_file().read_text(encoding="utf-8"), "[ 끊긴")
        self.assertEqual((server.calls, server.probes), ([], []))

    def test_interrupted_backfill_does_not_skip_the_gap_below_older_snapshot_rows(self) -> None:
        """예전 스냅샷의 최신 행이 남아 있어도 커서는 훑은 구간의 끝까지만 전진해야 한다."""
        newest = _trace(9)
        store.save_json(collect.collection_file(), [collect.row_of(newest, environments.DEV)])
        server = self._server([_trace(i) for i in range(1, 7)] + [newest])

        first = collect.sync(environments.DEV, window=_WINDOW, max_pages=1)

        self.assertFalse(first.completed)
        self.assertEqual(
            collect.load_state(environments.DEV)["last_timestamp"], _trace(1).timestamp.isoformat()
        )

        server.calls.clear()
        collect.sync(environments.DEV, window=_WINDOW)

        # 커서가 t009 로 튀었다면 t002~t006 이 영영 빠진다.
        self.assertEqual(server.calls[0]["from_timestamp"], _trace(1).timestamp)
        self.assertEqual(
            sorted(row["id"] for row in collect.load_rows()),
            ["t001", "t002", "t003", "t004", "t005", "t006", "t009"],
        )

    def test_legacy_timestamp_string_is_parsed(self) -> None:
        parsed = collect.parse_timestamp("2026-08-14 04:30:00.197000+00:00")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNone(collect.parse_timestamp(None))
        self.assertIsNone(collect.parse_timestamp("없는 시각"))


class MultiEnvironmentServer:
    """환경마다 다른 트레이스를 돌려주는 LangFuse 흉내(구간 조회·최신순)."""

    def __init__(self, by_environment: dict[str, list[SimpleNamespace]]) -> None:
        self.by_environment = by_environment
        self.calls: list[dict] = []

    def _picked(self, env, from_timestamp, to_timestamp):
        items = self.by_environment.get(env, [])
        return [t for t in items if from_timestamp <= t.timestamp < to_timestamp]

    def list_traces(self, *, from_timestamp, to_timestamp, env):
        self.calls.append({"from_timestamp": from_timestamp, "env": env})
        return sorted(self._picked(env, from_timestamp, to_timestamp), key=lambda t: t.timestamp, reverse=True)

    def has_traces(self, *, from_timestamp, to_timestamp, env):
        return bool(self._picked(env, from_timestamp, to_timestamp))


class MergedEnvironmentTests(SyncTestCase):
    """개발·운영을 한 목록에 합치되, 커서는 환경마다 따로 간다."""

    def _server(self, by_environment: dict[str, list[SimpleNamespace]]) -> MultiEnvironmentServer:
        server = MultiEnvironmentServer(by_environment)
        self._patch_server(server)
        return server

    def test_both_environments_land_in_one_time_sorted_list(self) -> None:
        self._server(
            {
                environments.DEV: [_trace(1), _trace(3)],
                environments.PROD: [_trace(2), _trace(4)],
            }
        )

        collect.sync_all([environments.DEV, environments.PROD], window=_WINDOW)

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

        collect.sync_all([environments.DEV, environments.PROD], window=_WINDOW)
        server.calls.clear()
        collect.sync(environments.PROD, window=_WINDOW)

        # 운영 재조회는 운영 커서(t005)부터. 개발 커서(t002)에 영향받지 않는다.
        self.assertEqual(server.calls[0]["env"], environments.PROD)
        self.assertEqual(server.calls[0]["from_timestamp"], _trace(5).timestamp)
        states = collect.load_states()
        self.assertEqual(states[environments.DEV]["last_timestamp"], _trace(2).timestamp.isoformat())
        self.assertEqual(states[environments.PROD]["last_timestamp"], _trace(5).timestamp.isoformat())

    def test_syncing_one_environment_keeps_the_other_environment_rows(self) -> None:
        self._server({environments.DEV: [_trace(1)], environments.PROD: [_trace(2)]})
        collect.sync_all([environments.DEV, environments.PROD], window=_WINDOW)

        result = collect.sync(environments.PROD, full=True, window=_WINDOW)

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
