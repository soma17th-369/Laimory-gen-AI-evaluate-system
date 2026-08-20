"""프롬프트 버전 레지스트리 (파일 기반).

채점 기준(rubric) 등 편집 가능한 프롬프트를 이름별로 버전 관리한다. 저장 위치는
``data/prompts/<name>/v<N>.json`` 이고 버전 번호는 1부터 증가한다. 일반 버전은 완전한
``content``를 저장하며, 여러 원본을 보존해 합치는 버전은 ``parts``에 앞선 버전 번호를
나열하고 ``content``를 마지막 보충 지침으로 사용한다.

핵심 규칙: **같은 본문(content)이면 새 버전을 만들지 않고 기존 버전을 재사용**한다.
그래서 같은 기준으로 여러 task 를 재채점해도 버전이 난립하지 않고, "버전 → 점수" 매핑이
1:1 로 유지된다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.storage import store
from app.storage.paths import prompt_dir, prompt_version_file


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _raw_versions(name: str) -> list[dict[str, Any]]:
    """저장된 원본 레코드를 번호 오름차순으로 읽는다."""
    out: list[dict[str, Any]] = []
    for path in store.list_json(prompt_dir(name)):
        data = store.load_json(path)
        if isinstance(data, dict) and isinstance(data.get("version"), int):
            out.append(data)
    out.sort(key=lambda d: d["version"])
    return out


def _resolve_content(
    record: dict[str, Any],
    by_version: dict[int, dict[str, Any]],
    resolving: frozenset[int] = frozenset(),
) -> str:
    """parts가 있는 합성 버전을 재귀적으로 펼쳐 완전한 본문을 만든다."""
    version = record["version"]
    if version in resolving:
        raise ValueError(f"프롬프트 버전 합성 순환 참조: v{version}")

    chunks: list[str] = []
    next_resolving = resolving | {version}
    for part_version in record.get("parts") or []:
        part = by_version.get(part_version)
        if part is None:
            raise ValueError(f"프롬프트 v{version}의 구성 버전 v{part_version}이 없습니다.")
        chunks.append(_resolve_content(part, by_version, next_resolving))
    own_content = record.get("content")
    if isinstance(own_content, str) and own_content.strip():
        chunks.append(own_content)
    return "\n\n".join(chunk.strip() for chunk in chunks if chunk.strip())


def list_versions(name: str) -> list[dict[str, Any]]:
    """이름의 모든 버전을 완전한 본문으로 해석해 번호 오름차순으로 반환한다."""
    raw = _raw_versions(name)
    by_version = {record["version"]: record for record in raw}
    resolved: list[dict[str, Any]] = []
    for record in raw:
        item = dict(record)
        item["content"] = _resolve_content(record, by_version)
        resolved.append(item)
    return resolved


def latest(name: str) -> dict[str, Any] | None:
    """가장 높은 번호의 버전. 없으면 None."""
    versions = list_versions(name)
    return versions[-1] if versions else None


def get(name: str, version: int) -> dict[str, Any] | None:
    """특정 버전. 없으면 None."""
    return next((record for record in list_versions(name) if record["version"] == version), None)


def get_or_create(name: str, content: str, *, note: str = "", source: str = "manual") -> dict[str, Any]:
    """본문이 기존 버전과 같으면 그 버전을 반환, 아니면 새 버전을 만들어 반환.

    source: 'manual'(명시적 저장) | 'judge'(채점 시 자동) | 'seed' 등 생성 맥락.
    """
    versions = list_versions(name)
    for v in versions:
        if v.get("content") == content:
            return v

    next_version = versions[-1]["version"] + 1 if versions else 1
    parent = versions[-1]["version"] if versions else None
    record: dict[str, Any] = {
        "name": name,
        "version": next_version,
        "createdAt": _now_iso(),
        "parent": parent,
        "note": (note or "").strip(),
        "source": source,
        "content": content,
    }
    store.save_json(prompt_version_file(name, next_version), record)
    return record
