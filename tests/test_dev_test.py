"""Dev 환경 테스트 — 요청 만들기·검사, 엔드포인트 호출 결과 해석, 실행 기록."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.devtest import client, request, runs
from app.ui import dev_test

KST = timezone(timedelta(hours=9))

_SNAPSHOT = {
    "taskId": "01a09980-2f4c-7559-a978-89341f60f4a1",
    "recordDate": "2026-09-11",
    "recordTimeZone": "Asia/Seoul",
    "userMemory": {"contentCaptured": False, "byteLength": 116, "sha256": "ab" * 32},
    "timelineWindow": {
        "startTime": "2026-09-11T00:00:00+09:00",
        "endTime": "2026-09-12T00:00:00+09:00",
    },
    "sourceItems": [
        {
            "rawId": "ba59c4a7-61ac-40d1-85bd-2947c2dad413",
            "itemType": "STAY",
            "startAt": "2026-09-10T22:26:09+09:00",
            "endAt": "2026-09-11T02:30:41+09:00",
            "payload": {"address": "가상 주소", "places": ["가상 장소"]},
        },
        {
            "rawId": "d27f7f1c-46af-4c82-a60e-000000000001",
            "itemType": "NOTIFICATION",
            "startAt": "2026-09-11T09:00:00+09:00",
            "endAt": None,
            "payload": {"appName": "가상앱", "title": "t", "text": "x"},
        },
        {
            "rawId": "e81b4cd8-7cef-4238-b16f-75865840abd4",
            "itemType": "HEALTH",
            "startAt": "2026-09-11T00:00:00+09:00",
            "endAt": "2026-09-12T00:00:00+09:00",
            "payload": {"metric": "STEPS", "value": 13492},
        },
    ],
}


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_read_from_normalize_input_first(self) -> None:
        observations = [
            SimpleNamespace(name="main-agent", input={"snapshot": {"sourceItems": "not-this"}}, output=None),
            SimpleNamespace(name="normalize-source-snapshot", input={"snapshot": _SNAPSHOT}, output=None),
        ]
        self.assertIs(request.snapshot_from_observations(observations), _SNAPSHOT)

    def test_falls_back_to_retrieve_output(self) -> None:
        observations = [{"name": "retrieve-source-snapshot", "input": {}, "output": {"snapshot": _SNAPSHOT}}]
        self.assertIs(request.snapshot_from_observations(observations), _SNAPSHOT)

    def test_missing_snapshot_is_none(self) -> None:
        self.assertIsNone(request.snapshot_from_observations([{"name": "main-agent", "input": {}}]))
        self.assertIsNone(request.snapshot_from_observations([]))

    def test_body_renames_window_and_drops_hashed_memory(self) -> None:
        body = request.body_from_snapshot(_SNAPSHOT)

        self.assertEqual(
            body["window"],
            {"startAt": "2026-09-11T00:00:00+09:00", "endAt": "2026-09-12T00:00:00+09:00"},
        )
        self.assertEqual(body["recordDate"], "2026-09-11")
        self.assertEqual(body["recordTimeZone"], "Asia/Seoul")
        self.assertNotIn("userMemory", body)
        self.assertNotIn("taskId", body)

    def test_every_item_is_kept_including_notifications(self) -> None:
        body = request.body_from_snapshot(_SNAPSHOT)

        self.assertEqual(
            [item["itemType"] for item in body["sourceItems"]], ["STAY", "NOTIFICATION", "HEALTH"]
        )
        self.assertEqual(body["sourceItems"][0], _SNAPSHOT["sourceItems"][0])

    def test_empty_notification_end_is_left_out(self) -> None:
        """알림은 수신 시각을 startAt 에만 담는다. 원본의 `endAt: null` 은 옮기지 않는다."""
        notification = request.body_from_snapshot(_SNAPSHOT)["sourceItems"][1]

        self.assertNotIn("endAt", notification)
        self.assertEqual(notification["payload"], _SNAPSHOT["sourceItems"][1]["payload"])

    def test_snapshot_body_passes_validation_without_warnings(self) -> None:
        check = request.validate(request.body_from_snapshot(_SNAPSHOT))

        self.assertTrue(check.ok, check.errors)
        self.assertEqual(check.warnings, ())


class ValidateTests(unittest.TestCase):
    def _body(self) -> dict:
        return copy.deepcopy(request.example_body())

    def test_example_is_valid(self) -> None:
        check = request.validate(self._body())
        self.assertTrue(check.ok, check.errors)
        self.assertEqual(check.warnings, ())
        self.assertEqual(check.item_types, {"STAY": 1, "NOTIFICATION": 1})

    def test_non_object_is_rejected(self) -> None:
        self.assertFalse(request.validate([1, 2]).ok)

    def test_required_top_level_fields(self) -> None:
        body = self._body()
        del body["recordDate"]
        del body["window"]
        body["sourceItems"] = []
        errors = " ".join(request.validate(body).errors)

        self.assertIn("recordDate", errors)
        self.assertIn("window", errors)
        self.assertIn("sourceItems", errors)

    def test_window_must_be_ordered_and_offset_aware(self) -> None:
        body = self._body()
        body["window"] = {"startAt": "2026-06-21T00:00:00+09:00", "endAt": "2026-06-20T00:00:00+09:00"}
        self.assertIn("앞서야", " ".join(request.validate(body).errors))

        body["window"] = {"startAt": "2026-06-20T00:00:00", "endAt": "2026-06-21T00:00:00+09:00"}
        self.assertIn("offset", " ".join(request.validate(body).errors))

    def test_raw_id_must_be_lowercase_uuid_and_unique(self) -> None:
        body = self._body()
        item = body["sourceItems"][0]
        body["sourceItems"].append(copy.deepcopy(item))
        body["sourceItems"].append({**item, "rawId": item["rawId"].upper()})
        errors = " ".join(request.validate(body).errors)

        self.assertIn("중복", errors)
        self.assertIn("소문자 UUID", errors)

    def test_item_type_and_start_are_required(self) -> None:
        body = self._body()
        del body["sourceItems"][0]["itemType"]
        del body["sourceItems"][0]["startAt"]
        errors = " ".join(request.validate(body).errors)

        self.assertIn("itemType", errors)
        self.assertIn("startAt", errors)

    def test_unknown_item_type_warns_but_does_not_block(self) -> None:
        """서버는 itemType 이 있는지만 본다. 모르는 값은 서버를 통과하므로 경고만."""
        body = self._body()
        body["sourceItems"][0]["itemType"] = "SMS"
        check = request.validate(body)

        self.assertTrue(check.ok)
        self.assertIn("SMS", " ".join(check.warnings))

    def _notification(self, body: dict) -> dict:
        return next(item for item in body["sourceItems"] if item["itemType"] == "NOTIFICATION")

    def test_notification_without_title_and_text_warns(self) -> None:
        """운영 경로는 400 으로 막지만 테스트 엔드포인트는 그대로 넘기는 알림."""
        body = self._body()
        self._notification(body)["payload"] = {"appName": "카카오톡", "title": " ", "text": None}
        check = request.validate(body)

        self.assertTrue(check.ok)
        self.assertIn("운영 경로라면 400", " ".join(check.warnings))

    def test_notification_with_only_text_is_fine(self) -> None:
        body = self._body()
        self._notification(body)["payload"] = {"appName": "카카오톡", "text": "점심 뭐 먹어?"}
        self.assertEqual(request.validate(body).warnings, ())

    def test_notification_end_warns(self) -> None:
        body = self._body()
        self._notification(body)["endAt"] = "2026-06-20T12:31:00+09:00"
        check = request.validate(body)

        self.assertTrue(check.ok)
        self.assertIn("`endAt` 은 넣지 않습니다", " ".join(check.warnings))

    def test_photo_without_downloadable_url_warns(self) -> None:
        """LangFuse 원본의 photoUrl 은 `[REDACTED]` 라 AI 가 사진을 받지 못한다."""
        body = self._body()
        item = body["sourceItems"][0]
        body["sourceItems"] = [
            {**item, "itemType": "PHOTO", "payload": {"photoUrl": "[REDACTED]"}},
            {
                **item,
                "rawId": "0198f2a1-7c3d-7000-8b2e-1f4a9c05d6e8",
                "itemType": "PHOTO",
                "payload": {"photoUrl": "https://example.test/p.jpg"},
            },
        ]
        check = request.validate(body)

        self.assertTrue(check.ok)
        self.assertIn("PHOTO 1건", " ".join(check.warnings))

    def test_body_over_one_megabyte_is_rejected(self) -> None:
        body = self._body()
        body["sourceItems"][0]["payload"] = {"blob": "가" * 400_000}
        check = request.validate(body)

        self.assertGreater(check.size_bytes, request.MAX_REQUEST_BYTES)
        self.assertIn("1MB", " ".join(check.errors))

    def test_parse_reports_position(self) -> None:
        body, error = request.parse('{"a": }')
        self.assertIsNone(body)
        self.assertIn("줄 1", error)


def _endpoint(token: str | None = "secret-token") -> client.Endpoint:
    return client.Endpoint(
        url="https://dev.example.test/t/api/1.0.0/timeline/test",
        access_token=SecretStr(token) if token is not None else None,
        timeout_seconds=180,
    )


def _send(handler, token: str | None = "secret-token") -> client.Outcome:
    return client.send(_endpoint(token), request.example_body(), transport=httpx.MockTransport(handler))


_SUCCESS = {
    "taskId": "0198f2a1-0000-7000-8000-000000000001",
    "timedOut": False,
    "events": [
        {
            "eventType": "MEAL",
            "title": "점심",
            "subtitle": None,
            "question": None,
            "place": "성수동 카페",
            "address": None,
            "startAt": "2026-06-20T12:00:00+09:00",
            "endAt": "2026-06-20T13:00:00+09:00",
            "sourceRawIds": ["0198f2a1-7c3d-7000-8b2e-1f4a9c05d6e7"],
        }
    ],
}


class SendTests(unittest.TestCase):
    def test_success_body_and_bearer_header(self) -> None:
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["auth"] = req.headers.get("Authorization")
            seen["method"] = req.method
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=_SUCCESS)

        outcome = _send(handler)

        self.assertEqual(seen["auth"], "Bearer secret-token")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["body"], request.example_body())
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.task_id, _SUCCESS["taskId"])
        self.assertFalse(outcome.timed_out)
        self.assertEqual(len(outcome.events), 1)
        self.assertEqual(outcome.failure_text(), "")

    def test_no_token_means_no_authorization_header(self) -> None:
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["has_auth"] = "Authorization" in req.headers
            return httpx.Response(200, json=_SUCCESS)

        _send(handler, token=None)
        self.assertFalse(seen["has_auth"])

    def test_timed_out_is_still_success(self) -> None:
        outcome = _send(lambda req: httpx.Response(200, json={**_SUCCESS, "timedOut": True}))
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.timed_out)

    def test_ai_error_code_header_is_explained(self) -> None:
        envelope = {"header": {"code": -1009, "message": "AI 처리 실패"}, "body": None}
        outcome = _send(
            lambda req: httpx.Response(502, json=envelope, headers={"X-Ai-Error-Code": "1202"})
        )

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, -1009)
        self.assertEqual(outcome.ai_error_code, "1202")
        text = outcome.failure_text()
        self.assertIn("HTTP 502", text)
        self.assertIn("-1009", text)
        self.assertIn("구조화 출력 실패", text)

    def test_502_without_ai_header_means_no_ai_response(self) -> None:
        envelope = {"header": {"code": -1009, "message": "timeout"}, "body": None}
        outcome = _send(lambda req: httpx.Response(502, json=envelope))
        self.assertIn("AI 응답을 받지 못함", outcome.failure_text())

    def test_non_json_response_keeps_text(self) -> None:
        outcome = _send(lambda req: httpx.Response(401, text="<html>Unauthorized</html>"))

        self.assertIsNone(outcome.body)
        self.assertIn("Unauthorized", outcome.text)
        self.assertIn("access token", outcome.failure_text())

    def test_timeout_becomes_outcome_not_exception(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("read timed out", request=req)

        outcome = _send(handler)

        self.assertIsNone(outcome.status)
        self.assertIn("시간 초과", outcome.failure_text())

    def test_connection_error_becomes_outcome(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=req)

        self.assertIn("ConnectError", _send(handler).failure_text())

    def test_record_round_trip(self) -> None:
        outcome = _send(lambda req: httpx.Response(200, json=_SUCCESS))
        self.assertEqual(client.Outcome.from_record(outcome.to_record()), outcome)


class EndpointTests(unittest.TestCase):
    def _settings(self, **values) -> Settings:
        return Settings(_env_file=None, **values)

    def test_missing_url_means_not_configured(self) -> None:
        self.assertIsNone(client.endpoint_from_settings(self._settings(timeline_test_url="  ")))

    def test_blank_token_is_treated_as_absent(self) -> None:
        endpoint = client.endpoint_from_settings(
            self._settings(timeline_test_url="https://x.test/t", timeline_test_access_token="")
        )
        self.assertFalse(endpoint.has_token)

    def test_token_and_timeout_are_read(self) -> None:
        endpoint = client.endpoint_from_settings(
            self._settings(
                timeline_test_url=" https://x.test/t ",
                timeline_test_access_token="abc",
                timeline_test_timeout_seconds=200,
            )
        )
        self.assertEqual(endpoint.url, "https://x.test/t")
        self.assertTrue(endpoint.has_token)
        self.assertEqual(endpoint.timeout_seconds, 200)
        self.assertNotIn("abc", repr(endpoint))


class RunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        for patch in (
            mock.patch.object(runs, "dev_test_dir", lambda: root),
            mock.patch.object(runs, "dev_test_run_file", lambda run_id: root / f"{run_id}.json"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)
        self.root = root

    def test_saved_newest_first_and_without_token(self) -> None:
        outcome = client.Outcome(status=200, elapsed_seconds=42.0, body=_SUCCESS)
        for minute in (1, 2):
            runs.save(
                endpoint=_endpoint("never-store-me"),
                body=request.example_body(),
                outcome=outcome,
                source={"kind": "example"},
                started_at=datetime(2026, 9, 18, 10, minute, tzinfo=KST),
            )

        records = runs.load_all()

        self.assertEqual([r["startedAt"] for r in records], ["2026-09-18T10:02:00+09:00", "2026-09-18T10:01:00+09:00"])
        self.assertEqual(records[0]["authorization"], "bearer")
        for path in self.root.glob("*.json"):
            self.assertNotIn("never-store-me", path.read_text(encoding="utf-8"))


class PageHelperTests(unittest.TestCase):
    _ITEMS = [
        {"rawId": "a", "itemType": "STAY"},
        {"rawId": "b", "itemType": "PHOTO"},
        {"rawId": "c", "itemType": "PHOTO"},
        {"rawId": "d", "itemType": "HEALTH"},
    ]
    _EVENTS = [
        {"eventType": "MEAL", "title": "점심", "startAt": "2026-06-20T12:00:00+09:00", "sourceRawIds": ["a", "b"]},
        {"eventType": "REST", "title": "휴식", "startAt": "2026-06-20T15:00:00+09:00", "sourceRawIds": ["b", "zz"]},
    ]

    def test_event_rows_explain_sources_by_item_type(self) -> None:
        rows = dev_test.event_rows(self._EVENTS, self._ITEMS)

        self.assertEqual(rows[0]["근거 원본"], "PHOTO 1 · STAY 1")
        self.assertEqual(rows[1]["근거 원본"], "? 1 · PHOTO 1")
        self.assertEqual(rows[0]["시작"], "06-20 12:00")
        self.assertEqual(rows[0]["끝"], "-")

    def test_unused_sources_are_counted_by_type(self) -> None:
        self.assertEqual(dict(dev_test.unused_sources(self._EVENTS, self._ITEMS)), {"PHOTO": 1, "HEALTH": 1})

    def test_source_label(self) -> None:
        self.assertEqual(dev_test.source_label({"kind": "example"}), "예시")
        self.assertEqual(
            dev_test.source_label({"kind": "trace", "taskId": "01a09980-2f4c", "edited": True}),
            "dev 트레이스 01a09980 (편집)",
        )
        self.assertEqual(dev_test.source_label({"kind": "manual"}), "직접 입력")

    def test_run_rows(self) -> None:
        ok = {
            "runId": "r1",
            "startedAt": "2026-09-18T10:00:00+09:00",
            "source": {"kind": "example"},
            "request": {"sourceItems": self._ITEMS},
            "response": client.Outcome(200, 61.24, body=_SUCCESS).to_record(),
        }
        failed = {
            "runId": "r2",
            "startedAt": "2026-09-18T10:05:00+09:00",
            "source": {"kind": "manual"},
            "request": {"sourceItems": []},
            "response": client.Outcome(502, 3.0, body={"header": {}}, ai_error_code="1301").to_record(),
        }

        rows = dev_test.run_rows([ok, failed])

        self.assertEqual(rows[0]["결과"], "성공")
        self.assertEqual(rows[0]["소요(초)"], 61.2)
        self.assertEqual(rows[0]["이벤트"], "1")
        self.assertEqual(rows[0]["원본"], 4)
        self.assertEqual(rows[0]["taskId"], _SUCCESS["taskId"])
        self.assertEqual(rows[1]["결과"], "HTTP 502 · AI 1301")
        self.assertEqual(rows[1]["이벤트"], "-")


if __name__ == "__main__":
    unittest.main()
