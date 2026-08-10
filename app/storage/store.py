"""json 저장/로드/목록 유틸. 한글은 그대로(ensure_ascii=False), 부모 폴더는 자동 생성."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_json(path: Path, data: Any) -> Path:
    """dict/list(또는 pydantic model_dump 결과)를 json 으로 저장. 부모 폴더 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_json(path: Path) -> Any | None:
    """없으면 None. 깨진 json 도 None(호출부가 판단)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_json(directory: Path) -> list[Path]:
    """디렉터리 안의 *.json 경로 목록(이름순). 없으면 빈 리스트."""
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.json") if p.is_file())
