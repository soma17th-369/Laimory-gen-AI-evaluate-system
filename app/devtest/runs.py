"""실행 기록 — 테스트 엔드포인트를 부를 때마다 요청·응답을 파일 하나로 남긴다.

한 번에 수십 초 ~ 약 150초와 LLM 비용이 드는 호출이라 결과를 화면에만 두지 않는다. 저장 위치는
`data/dev-test/<runId>.json`(gitignore). 토큰은 남기지 않고, 인증 헤더를 붙였는지만 적는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.devtest.client import Endpoint, Outcome
from app.storage import store
from app.storage.paths import dev_test_dir, dev_test_run_file


def save(
    *,
    endpoint: Endpoint,
    body: Any,
    outcome: Outcome,
    source: dict[str, Any],
    started_at: datetime,
) -> dict[str, Any]:
    """기록 하나를 저장하고 그대로 돌려준다. runId 는 시작 시각이라 이름순 = 시간순."""
    run_id = started_at.strftime("%Y%m%d-%H%M%S-%f")
    record = {
        "runId": run_id,
        "startedAt": started_at.isoformat(timespec="seconds"),
        "url": endpoint.url,
        "authorization": "bearer" if endpoint.has_token else "none",
        "source": source,
        "request": body,
        "response": outcome.to_record(),
    }
    store.save_json(dev_test_run_file(run_id), record)
    return record


def load_all() -> list[dict[str, Any]]:
    """저장된 기록 전부, 최신순."""
    records = []
    for path in reversed(store.list_json(dev_test_dir())):
        data = store.load_json(path)
        if isinstance(data, dict) and data.get("runId"):
            records.append(data)
    return records
