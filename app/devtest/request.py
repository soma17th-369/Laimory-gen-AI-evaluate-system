"""타임라인 AI 테스트 요청 body — 예시·수집 원본에서 만들기, 보내기 전 검사.

엔드포인트(`POST /t/api/{applicationVersion}/timeline/test`)의 body 는 운영 경로의 AI 입력 조회
응답에서 `taskId`·`taskToken` 을 뺀 형태다.

```
{recordDate, recordTimeZone?, window{startAt, endAt}, userMemory?,
 sourceItems[{rawId, itemType, startAt, endAt?, payload?}]}
```

운영 경로가 LangFuse 에 남기는 원본 스냅샷(`normalize-source-snapshot.input.snapshot`)은 거의 같은
모양이라 필드 이름 두 개(`timelineWindow.startTime/endTime` → `window.startAt/endAt`)만 바꾸면 된다.
`userMemory` 는 LangFuse 에 해시만 남으므로(`contentCaptured: false`) 옮기지 않는다.

[validate][app.devtest.request.validate] 는 서버가 400 으로 돌려보낼 조건을 미리 잡는다(오류). 서버는
막지 않지만 운영 경로와 조건이 달라지는 것은 경고로만 알린다.

- `itemType` — 서버는 값이 있는지만 보고 종류는 제한하지 않는다. 서버 `ItemType` 에 없는 값은 경고.
- 알림(`NOTIFICATION`) — 한 시점 기록이라 수신 시각은 `startAt` 에만 담고 `endAt` 은 넣지 않는다.
  운영 경로는 `payload.title`·`text` 가 둘 다 없으면 400 으로 막지만 테스트 엔드포인트는 그대로
  AI 로 넘긴다. 운영과 같은 조건으로 시험하려면 둘 중 하나는 채운다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

ITEM_TYPES: tuple[str, ...] = ("PHOTO", "CALENDAR", "STAY", "MOVEMENT", "HEALTH", "NOTIFICATION")
"""대상 서버 `ItemType` enum 의 전체 값. 테스트 엔드포인트는 값 종류를 따로 막지 않는다."""

MAX_REQUEST_BYTES = 1024 * 1024
"""서버 요청 body 상한(`APP_AI_TIMELINE_TEST_MAX_REQUEST_BYTES` 기본 1MB)."""

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
"""서버가 받는 rawId — canonical 소문자 UUID."""

_SNAPSHOT_OBSERVATIONS = (
    ("normalize-source-snapshot", "input"),
    ("retrieve-source-snapshot", "output"),
)
"""원본 스냅샷이 실리는 관측치와 위치. 앞의 것을 먼저 본다."""


def example_body() -> dict[str, Any]:
    """형식 확인용 최소 예시. 값은 가상이다."""
    return {
        "recordDate": "2026-06-20",
        "recordTimeZone": "Asia/Seoul",
        "window": {
            "startAt": "2026-06-20T00:00:00+09:00",
            "endAt": "2026-06-21T00:00:00+09:00",
        },
        "sourceItems": [
            {
                "rawId": "0198f2a1-7c3d-7000-8b2e-1f4a9c05d6e7",
                "itemType": "STAY",
                "startAt": "2026-06-20T12:00:00+09:00",
                "endAt": "2026-06-20T13:00:00+09:00",
                "payload": {
                    "latitude": 37.5445,
                    "longitude": 127.0559,
                    "address": "서울 성동구 성수이로 1",
                    "places": ["성수동 카페"],
                },
            },
            {
                "rawId": "0198f2a1-7c3d-7000-8b2e-1f4a9c05d6e8",
                "itemType": "NOTIFICATION",
                "startAt": "2026-06-20T12:30:00+09:00",
                "payload": {"appName": "카카오톡", "title": "홍길동", "text": "점심 뭐 먹어?"},
            },
        ],
    }


def _field(obj: Any, name: str) -> Any:
    """LangFuse SDK 객체와 dict(저장본·테스트) 양쪽에서 필드를 읽는다."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def snapshot_from_observations(observations: Iterable[Any]) -> dict[str, Any] | None:
    """트레이스 관측치에서 원본 스냅샷을 찾는다. 없으면 None."""
    by_name = {}
    for obs in observations or []:
        by_name.setdefault(_field(obs, "name"), obs)
    for name, where in _SNAPSHOT_OBSERVATIONS:
        obs = by_name.get(name)
        container = _field(obs, where) if obs is not None else None
        snapshot = container.get("snapshot") if isinstance(container, dict) else None
        if isinstance(snapshot, dict) and isinstance(snapshot.get("sourceItems"), list):
            return snapshot
    return None


def body_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """원본 스냅샷 → 테스트 요청 body. 항목은 전부 옮기고, 비어 있는 `endAt`(알림)은 넣지 않는다."""
    window = snapshot.get("timelineWindow") or snapshot.get("window") or {}
    items: list[dict[str, Any]] = []
    for item in snapshot.get("sourceItems") or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                key: item[key]
                for key in ("rawId", "itemType", "startAt", "endAt", "payload")
                if key in item and not (key == "endAt" and item[key] is None)
            }
        )
    body: dict[str, Any] = {
        "recordDate": snapshot.get("recordDate"),
        "recordTimeZone": snapshot.get("recordTimeZone"),
        "window": {
            "startAt": window.get("startTime") or window.get("startAt") or window.get("start"),
            "endAt": window.get("endTime") or window.get("endAt") or window.get("end"),
        },
        "sourceItems": items,
    }
    if body["recordTimeZone"] is None:
        del body["recordTimeZone"]
    return body


def encode(body: Any) -> bytes:
    """서버로 보내는 바이트 그대로. 크기 검사도 이것으로 한다."""
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class Check:
    """보내기 전 검사 결과. errors 가 있으면 서버가 400 으로 돌려보낼 요청이다."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    item_types: dict[str, int]
    size_bytes: int

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _indexes(indexes: list[int]) -> str:
    shown = ", ".join(str(index) for index in indexes[:5])
    return f"{shown} …" if len(indexes) > 5 else shown


def parse(text: str) -> tuple[Any, str | None]:
    """편집창 문자열 → JSON. 실패하면 (None, 이유)."""
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"JSON 형식이 아닙니다: {exc.msg} (줄 {exc.lineno}, 칸 {exc.colno})"


def validate(body: Any) -> Check:
    """서버가 400 으로 막는 조건(명세 기준)을 미리 확인한다."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(body, dict):
        return Check(("body 는 JSON 객체여야 합니다.",), (), {}, 0)

    size = len(encode(body))
    if size > MAX_REQUEST_BYTES:
        errors.append(f"요청이 {size:,}바이트로 서버 상한(1MB)을 넘습니다.")

    record_date = body.get("recordDate")
    try:
        if not isinstance(record_date, str) or len(record_date) != 10:
            raise ValueError
        date.fromisoformat(record_date)
    except ValueError:
        errors.append("`recordDate` 가 없거나 `yyyy-MM-dd` 형식이 아닙니다.")

    time_zone = body.get("recordTimeZone")
    if time_zone is not None and not isinstance(time_zone, str):
        errors.append("`recordTimeZone` 은 문자열이어야 합니다.")

    window = body.get("window")
    if not isinstance(window, dict):
        errors.append("`window` 가 없습니다(이 엔드포인트는 필수).")
    else:
        bounds = {}
        for key in ("startAt", "endAt"):
            parsed = _parse_time(window.get(key))
            if parsed is None:
                errors.append(f"`window.{key}` 가 없거나 ISO-8601 형식이 아닙니다.")
            elif parsed.tzinfo is None:
                errors.append(f"`window.{key}` 에 offset(예: +09:00)이 없습니다.")
            else:
                bounds[key] = parsed
        if len(bounds) == 2 and not bounds["startAt"] < bounds["endAt"]:
            errors.append("`window.startAt` 이 `window.endAt` 보다 앞서야 합니다.")

    items = body.get("sourceItems")
    item_types: Counter[str] = Counter()
    if not isinstance(items, list) or not items:
        errors.append("`sourceItems` 가 1건 이상 있어야 합니다.")
        items = []
    seen: Counter[str] = Counter()
    photos_without_url = 0
    notifications_with_end: list[int] = []
    notifications_without_text: list[int] = []
    for index, item in enumerate(items):
        where = f"`sourceItems[{index}]`"
        if not isinstance(item, dict):
            errors.append(f"{where} 가 객체가 아닙니다.")
            continue
        raw_id = item.get("rawId")
        if not isinstance(raw_id, str) or not _UUID.match(raw_id):
            errors.append(f"{where}.rawId 가 소문자 UUID 가 아닙니다: {raw_id!r}")
        else:
            seen[raw_id] += 1
        item_type = item.get("itemType")
        if not isinstance(item_type, str) or not item_type:
            errors.append(f"{where}.itemType 이 없습니다.")
        else:
            item_types[item_type] += 1
        start = _parse_time(item.get("startAt"))
        if start is None:
            errors.append(f"{where}.startAt 이 없거나 ISO-8601 형식이 아닙니다.")
        elif start.tzinfo is None:
            warnings.append(f"{where}.startAt 에 offset 이 없습니다.")
        if item.get("endAt") is not None and _parse_time(item.get("endAt")) is None:
            errors.append(f"{where}.endAt 이 ISO-8601 형식이 아닙니다.")
        if item_type == "PHOTO":
            payload = item.get("payload")
            photo_url = payload.get("photoUrl") if isinstance(payload, dict) else None
            if not (isinstance(photo_url, str) and photo_url.startswith(("http://", "https://"))):
                photos_without_url += 1
        if item_type == "NOTIFICATION":
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if item.get("endAt") is not None:
                notifications_with_end.append(index)
            if not any(str(payload.get(key) or "").strip() for key in ("title", "text")):
                notifications_without_text.append(index)

    duplicated = sorted(raw_id for raw_id, count in seen.items() if count > 1)
    if duplicated:
        errors.append(f"rawId 가 중복됩니다: {', '.join(duplicated)}")

    unknown = sorted(item_type for item_type in item_types if item_type not in ITEM_TYPES)
    if unknown:
        warnings.append(
            f"서버 ItemType({' '.join(ITEM_TYPES)})에 없는 값: {', '.join(unknown)} — 서버는 그대로 "
            "넘기지만 AI 가 거절하거나 무시할 수 있습니다."
        )
    if notifications_without_text:
        warnings.append(
            f"알림 {len(notifications_without_text)}건(sourceItems {_indexes(notifications_without_text)})에 "
            "`payload.title`·`text` 가 둘 다 없습니다 — 운영 경로라면 400 으로 막히는 알림입니다. "
            "테스트 엔드포인트는 그대로 AI 로 넘기니, 운영과 같은 조건으로 시험하려면 둘 중 하나를 채우세요."
        )
    if notifications_with_end:
        warnings.append(
            f"알림 {len(notifications_with_end)}건(sourceItems {_indexes(notifications_with_end)})에 `endAt` 이 "
            "있습니다 — 알림은 한 시점 기록이라 수신 시각을 `startAt` 에만 담고 `endAt` 은 넣지 않습니다."
        )
    if photos_without_url:
        warnings.append(
            f"PHOTO {photos_without_url}건의 `payload.photoUrl` 이 http(s) 주소가 아닙니다 — AI 가 사진을 "
            "받지 못해 사진 내용 판단은 시험되지 않습니다. LangFuse 원본은 photoUrl 이 `[REDACTED]` 로 남습니다."
        )
    return Check(tuple(errors), tuple(warnings), dict(item_types), size)
