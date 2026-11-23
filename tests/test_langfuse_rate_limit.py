from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from langfuse.api.core.api_error import ApiError
from pydantic import SecretStr

from app import langfuse_client


class RateLimitWaitTests(unittest.TestCase):
    """호출 한도(429)는 기다렸다가 다시 부르고, 다른 오류는 그대로 올린다."""

    def test_waits_for_retry_after_then_calls_again(self) -> None:
        answers = [ApiError(status_code=429, headers={"Retry-After": "7"}), "ok"]

        def call():
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(langfuse_client.time, "sleep") as sleep:
            self.assertEqual(langfuse_client._wait_on_rate_limit(call), "ok")

        sleep.assert_called_once_with(8.0)

    def test_other_errors_are_not_retried(self) -> None:
        call = mock.Mock(side_effect=ApiError(status_code=500))

        with mock.patch.object(langfuse_client.time, "sleep") as sleep:
            with self.assertRaises(ApiError):
                langfuse_client._wait_on_rate_limit(call)

        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    def test_gives_up_when_the_limit_never_clears(self) -> None:
        call = mock.Mock(side_effect=ApiError(status_code=429, headers={}))

        with mock.patch.object(langfuse_client.time, "sleep") as sleep:
            with self.assertRaises(ApiError):
                langfuse_client._wait_on_rate_limit(call)

        self.assertEqual(call.call_count, langfuse_client.RATE_LIMIT_MAX_WAITS + 1)
        sleep.assert_called_with(langfuse_client.RATE_LIMIT_DEFAULT_WAIT_SECONDS + 1)


_T0 = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)


def _obs(obs_id: str, *, trace_id: str = "trace-a", seconds: float = 0, **fields) -> SimpleNamespace:
    """v2 관측치 흉내. 필드 이름은 SDK 의 ObservationV2 와 같다."""
    start = _T0 + timedelta(seconds=seconds)
    values = {
        "id": obs_id,
        "trace_id": trace_id,
        "parent_observation_id": None,
        "is_root_observation": False,
        "type": "SPAN",
        "name": obs_id,
        "level": None,
        "status_message": None,
        "start_time": start,
        "end_time": start + timedelta(seconds=1),
        "latency": 1.0,
        "metadata": None,
        "input": None,
        "output": None,
        "usage_details": None,
        "total_cost": None,
        "session_id": None,
        "user_id": None,
        "trace_name": None,
        "tags": None,
    }
    values.update(fields)
    return SimpleNamespace(**values)


def _page(data, cursor=None) -> SimpleNamespace:
    return SimpleNamespace(data=list(data), meta=SimpleNamespace(cursor=cursor))


def _client(get_many) -> mock.Mock:
    client = mock.Mock()
    client.api.observations.get_many.side_effect = get_many
    return client


class GetTraceTests(unittest.TestCase):
    def _get(self, *answers):
        client = _client(list(answers))
        with mock.patch.object(langfuse_client, "get_client", return_value=client):
            return langfuse_client.get_trace("trace-a", "dev"), client

    def test_waits_for_the_rate_limit_like_the_list_call(self) -> None:
        root = _obs("root", is_root_observation=True)
        with mock.patch.object(langfuse_client.time, "sleep") as sleep:
            detail, _ = self._get(ApiError(status_code=429, headers={"Retry-After": "2"}), _page([root]))

        self.assertEqual(detail.id, "trace-a")
        sleep.assert_called_once_with(3.0)

    def test_trace_without_observations_has_its_own_error(self) -> None:
        with self.assertRaises(langfuse_client.TraceNotFound):
            self._get(_page([]))

    def test_other_errors_stay_as_they_are(self) -> None:
        with self.assertRaises(ApiError):
            self._get(ApiError(status_code=500))

    def test_detail_is_rebuilt_from_the_observations_of_the_trace(self) -> None:
        """예전 상세처럼 트레이스 입력·출력은 루트 것이고, 입출력 문자열은 풀려 있어야 한다."""
        root = _obs(
            "root",
            # 대상 서버 루트는 상위 서비스 span 아래에 있어 부모 id 가 남아 있다.
            parent_observation_id="upstream-span",
            is_root_observation=True,
            name="generate-timeline",
            trace_name="generate-timeline",
            session_id="task-1",
            user_id="",
            tags=["timeline"],
            input='{"taskId": "task-1", "request": {"date": "2026-11-20"}}',
            output='{"status": "COMPLETED"}',
            status_message="",
        )
        child = _obs("child", parent_observation_id="root", level=SimpleNamespace(value="WARNING"))
        generation = _obs(
            "gen",
            seconds=2,
            parent_observation_id="child",
            type="GENERATION",
            input="그냥 글",
            output='[{"role": "assistant"}]',
            model="gpt-5.4-mini",
            usage_details={"input": 10, "output": 2, "total": 12},
            total_cost=0.25,
        )

        detail, client = self._get(_page([generation, child, root]))

        self.assertEqual(
            client.api.observations.get_many.call_args.kwargs["fields"], langfuse_client.DETAIL_FIELDS
        )
        self.assertEqual(
            (detail.name, detail.timestamp, detail.session_id, detail.user_id, detail.tags),
            ("generate-timeline", _T0, "task-1", None, ["timeline"]),
        )
        self.assertEqual(detail.input["request"]["date"], "2026-11-20")
        self.assertEqual(detail.output, {"status": "COMPLETED"})
        self.assertEqual(detail.total_cost, 0.25)
        # 같은 시각이면 부모가 먼저, 그다음 시작 순.
        self.assertEqual([item.id for item in detail.observations], ["root", "child", "gen"])
        by_id = {item.id: item for item in detail.observations}
        self.assertIsNone(by_id["root"].status_message)
        self.assertEqual(by_id["child"].level, "WARNING")
        self.assertEqual(by_id["gen"].input, "그냥 글")
        self.assertEqual(by_id["gen"].output, [{"role": "assistant"}])
        self.assertEqual(by_id["gen"].model, "gpt-5.4-mini")

    def test_pages_are_followed_until_the_cursor_ends(self) -> None:
        """빈 페이지에도 커서가 붙어 올 수 있다."""
        first, last = _obs("root", is_root_observation=True), _obs("late", seconds=5)

        detail, client = self._get(_page([first], "c1"), _page([], "c2"), _page([last]))

        self.assertEqual([item.id for item in detail.observations], ["root", "late"])
        cursors = [call.kwargs["cursor"] for call in client.api.observations.get_many.call_args_list]
        self.assertEqual(cursors, [None, "c1", "c2"])


class ListTracesTests(unittest.TestCase):
    def test_traces_come_from_root_observations_with_summed_cost(self) -> None:
        roots = [
            # 옛 트레이스 id 를 재사용한 테스트: 루트가 둘이면 먼저 시작한 쪽이 그 트레이스다.
            _obs("a-late", seconds=30, is_root_observation=True, trace_name="generate-timeline", session_id="task-a"),
            _obs("a-first", seconds=10, is_root_observation=True, trace_name="generate-timeline", session_id="task-a"),
            _obs("b", trace_id="trace-b", is_root_observation=True, name="get_job", latency=None,
                 end_time=_T0),
        ]
        costs = [
            _obs("a1", total_cost=0.1),
            _obs("a2", total_cost=0.2),
            _obs("other", trace_id="trace-z", total_cost=0.9),
        ]
        seen = []

        def get_many(**kwargs):
            seen.append(kwargs)
            return _page(roots if kwargs.get("is_root_observation") else costs)

        client = _client(get_many)
        with mock.patch.object(langfuse_client, "get_client", return_value=client):
            summaries = langfuse_client.list_traces(
                from_timestamp=_T0, to_timestamp=_T0 + timedelta(days=1), env="prod"
            )

        by_id = {item.id: item for item in summaries}
        self.assertEqual(set(by_id), {"trace-a", "trace-b"})
        self.assertEqual(by_id["trace-a"].timestamp, _T0 + timedelta(seconds=10))
        self.assertEqual((by_id["trace-a"].name, by_id["trace-a"].session_id), ("generate-timeline", "task-a"))
        self.assertEqual(by_id["trace-a"].total_cost, 0.3)
        # 이름이 traceName 에 없으면 루트 이름, 시작=끝이면 latency 0, 비용 없으면 0.
        self.assertEqual((by_id["trace-b"].name, by_id["trace-b"].latency, by_id["trace-b"].total_cost), ("get_job", 0.0, 0.0))

        cost_call = seen[1]
        conditions = json.loads(cost_call["filter"])
        self.assertIn({"type": "number", "column": "totalCost", "operator": ">", "value": 0}, conditions)
        upper = next(c for c in conditions if c["column"] == "startTime" and c["operator"] == "<")
        self.assertEqual(upper["value"], (_T0 + timedelta(days=1) + langfuse_client.COST_SLACK).isoformat())

    def test_window_without_roots_skips_the_cost_call(self) -> None:
        client = _client(lambda **_kwargs: _page([]))
        with mock.patch.object(langfuse_client, "get_client", return_value=client):
            summaries = langfuse_client.list_traces(
                from_timestamp=_T0, to_timestamp=_T0 + timedelta(days=1), env="prod"
            )

        self.assertEqual(summaries, [])
        self.assertEqual(client.api.observations.get_many.call_count, 1)

    def test_has_traces_asks_for_a_single_root(self) -> None:
        client = _client(lambda **_kwargs: _page([_obs("root", is_root_observation=True)]))
        with mock.patch.object(langfuse_client, "get_client", return_value=client):
            found = langfuse_client.has_traces(from_timestamp=_T0, to_timestamp=_T0, env="dev")

        self.assertTrue(found)
        kwargs = client.api.observations.get_many.call_args.kwargs
        self.assertEqual((kwargs["limit"], kwargs["is_root_observation"]), (1, True))


class ClientTests(unittest.TestCase):
    def test_client_does_not_send_its_own_traces(self) -> None:
        """켜 두면 MCP 서버의 도구 호출 span 까지 그 LangFuse 프로젝트에 트레이스로 올라간다."""
        credentials = SimpleNamespace(
            is_complete=True, public_key=SecretStr("pk"), secret_key=SecretStr("sk"), host="https://example"
        )
        settings = mock.Mock()
        settings.langfuse_credentials.return_value = credentials
        with (
            mock.patch.dict(langfuse_client._clients, clear=True),
            mock.patch.object(langfuse_client, "get_settings", return_value=settings),
            mock.patch.object(langfuse_client, "Langfuse") as constructor,
        ):
            langfuse_client.get_client("dev")

        self.assertIs(constructor.call_args.kwargs["tracing_enabled"], False)

if __name__ == "__main__":
    unittest.main()
