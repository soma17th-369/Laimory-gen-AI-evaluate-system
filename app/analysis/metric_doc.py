"""메트릭 문서(`assets/rubrics/laimory-metric-v5.md`) 읽기·자르기.

채점 기준의 **정본은 문서**다. 코드가 기준 문장을 따로 들고 있지 않고, 이 모듈이 문서를
heading 단위로 잘라 그대로 프롬프트에 넣는다. 문서를 고치면 채점 기준이 같이 바뀐다.

자르는 단위는 heading 번호다(`1`, `1.1`, `2.3`, `5.5` …). `section()` 은 그 heading 과 **하위
heading 전부**를 돌려주고, `intro()` 는 하위 heading 직전까지만 돌려준다(예: `## 1. Event Agent`
의 안내 문장 한 줄).

요약·발췌는 하지 않는다. 항목 문장이 한 줄이라도 빠지면 채점 기준이 달라지기 때문이다.
누락 검사는 [app.analysis.stages][] 가 배점표와 대조해서 한다.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

DOCUMENT = _PROJECT_ROOT / "assets" / "rubrics" / "laimory-metric-v5.md"
"""메트릭 문서. 대상 서버 문서와 같은 취급으로 저장소에 원문을 둔다(`data/` 는 gitignore)."""

_HEADING = re.compile(r"^(#{2,4})\s+(.*?)\s*$")
_LEADING_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\b")
_HTML_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


class MetricDocumentError(RuntimeError):
    """문서를 읽을 수 없거나 기대한 절이 없을 때."""


@lru_cache(maxsize=1)
def load_text() -> str:
    """문서 원문. 맨 앞 HTML 주석(메타)은 프롬프트에 넣지 않는다."""
    try:
        raw = DOCUMENT.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetricDocumentError(f"메트릭 문서를 읽을 수 없습니다: {DOCUMENT}") from exc
    return _HTML_COMMENT.sub("", raw, count=1).strip()


@lru_cache(maxsize=1)
def _headings() -> tuple[tuple[str, int, int], ...]:
    """(번호, level, 시작 줄 index) 목록. 번호가 없는 heading 은 제목 전체를 번호로 쓴다."""
    found: list[tuple[str, int, int]] = []
    for index, line in enumerate(load_text().splitlines()):
        match = _HEADING.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        title = match.group(2)
        number = _LEADING_NUMBER.match(title)
        found.append((number.group(1) if number else title, level, index))
    return tuple(found)


def _slice(number: str, *, with_children: bool) -> str:
    lines = load_text().splitlines()
    headings = _headings()
    for position, (key, level, start) in enumerate(headings):
        if key != number:
            continue
        end = len(lines)
        for next_key, next_level, next_start in headings[position + 1 :]:
            if with_children and next_level > level:
                continue
            end = next_start
            break
        return "\n".join(lines[start:end]).strip()
    raise MetricDocumentError(f"메트릭 문서에 `{number}` 절이 없습니다.")


def section(number: str) -> str:
    """그 절과 하위 절 전부. 예: `section("1.2")` → Location Agent 기준 전체."""
    return _slice(number, with_children=True)


def intro(number: str) -> str:
    """그 절에서 **하위 절이 시작되기 전까지**. 예: `intro("1")` → Event Agent 합산 규칙 한 줄."""
    return _slice(number, with_children=False)


@lru_cache(maxsize=1)
def preamble() -> str:
    """문서 목적과 판정 용어. 모든 단계 프롬프트 맨 앞에 그대로 붙는다.

    번호가 붙은 첫 장(`## 1. …`) 직전까지가 공통 머리말이다. 그 앞의 `## 문서 목적`·
    `### 판정 용어` 는 번호가 없어 heading 번호로 집을 수 없다.
    """
    lines = load_text().splitlines()
    first_numbered = next(
        (start for key, _, start in _headings() if _LEADING_NUMBER.match(key)),
        len(lines),
    )
    return "\n".join(lines[:first_numbered]).strip()


def score_format() -> str:
    """점수 작성 형식(6장). 항목 합 = 총점 규칙이 여기 있다."""
    return section("6")


def split_by_markers(text: str, markers: list[str]) -> tuple[str, dict[str, str]]:
    """절 본문을 항목 구절(marker) 기준으로 자른다. → (앞머리, {marker: 블록}).

    heading level 로 자르지 않는 이유: 문서에는 항목 안에 같은 level 의 heading 이 들어 있는
    자리가 있다(예: `### 5.3` 안의 `### user memory 고정 필드`). 항목의 끝은 **다음 항목이
    시작하는 지점**이지 heading level 이 아니다.
    """
    positions: list[tuple[int, str]] = []
    for marker in markers:
        if not marker:
            raise MetricDocumentError("빈 구절로는 절을 자를 수 없습니다(항목의 marker 가 비었습니다).")
        index = text.find(marker)
        if index < 0:
            raise MetricDocumentError(f"기준 문서에서 `{marker}` 를 찾지 못했습니다.")
        # 표 한 줄짜리 항목은 marker 가 줄 가운데(LLM 확인 칸)에 있다. 항상 줄 처음부터 자른다.
        positions.append((text.rfind("\n", 0, index) + 1, marker))
    positions.sort()

    blocks: dict[str, str] = {}
    for order, (start, marker) in enumerate(positions):
        end = positions[order + 1][0] if order + 1 < len(positions) else len(text)
        blocks[marker] = text[start:end].strip()
    lead = text[: positions[0][0]].strip() if positions else text.strip()
    return lead, blocks


def table_row_cells(line: str) -> list[str]:
    """markdown 표 한 줄을 셀 목록으로. 표 줄이 아니면 빈 리스트."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]
