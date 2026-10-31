"""평가 대상(단계)과 배점표 — 단계별 채점의 **유일한 정본**.

메트릭 문서는 평가 대상을 8개로 나누고 각 대상을 100점으로 채점한다. 이 모듈은 그 8개와
항목·배점을 코드로 고정하고, 각 항목이 문서의 어느 구절에서 왔는지(`marker`)를 함께 들고 있다.

- 항목 문장 자체는 코드에 복사하지 않는다. [criteria][app.analysis.stages.criteria] 가 문서에서
  **항목별 확인 기준을 원문 그대로** 잘라 붙인다(요약·발췌 금지). 절을 통째로 붓지 않고 항목 키에
  묶어 두기 때문에, 어느 기준이 어느 배점에 속하는지가 프롬프트에서도 화면에서도 분명하다.
- `marker` 는 문서에서 그 항목이 시작하는 구절이다(heading 한 줄이거나 표 한 줄). 문서에서 항목이
  사라지거나 배점이 바뀌면 [validate][app.analysis.stages.validate] 가 실패해 **조용히 일부만
  채점되는 상태**를 막는다.
- 그래서 문서의 배점을 고치면 이 표도 같은 커밋에서 고쳐야 한다.

Sleep/Activity Agent 는 문서에서 deprecated 라 대상에 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.analysis import metric_doc, rubric_store

TIMELINE_TRACE = "generate-timeline"
USER_MEMORY_TRACE = "update-user-memory"
"""단계가 어느 트레이스에서 나오는지. User Memory 만 별도 트레이스다."""


@dataclass(frozen=True)
class RubricItem:
    """채점 항목 하나. `points` 는 문서의 배점, `marker` 는 문서에서의 위치 근거."""

    key: str
    """결과 스키마의 field 이름이 되므로 파이썬 식별자여야 한다."""
    label: str
    points: int
    marker: str
    """문서 절에 반드시 포함돼야 하는 구절(누락·배점 변경 감지용)."""


@dataclass(frozen=True)
class StageSpec:
    """평가 대상 하나."""

    key: str
    label: str
    trace_name: str
    doc_intro: tuple[str, ...]
    """항목 절 앞에 붙일 문서 절(하위 절 제외). 예: Event Agent 의 합산 규칙."""
    doc_sections: tuple[str, ...]
    """항목이 들어 있는 문서 절(하위 절 포함)."""
    items: tuple[RubricItem, ...]

    @property
    def total_points(self) -> int:
        return sum(item.points for item in self.items)

    def item(self, key: str) -> RubricItem:
        for item in self.items:
            if item.key == key:
                return item
        raise KeyError(f"{self.key} 단계에 `{key}` 항목이 없습니다.")


# 1.1 공통 기준 — Event Agent 4종이 같이 쓴다.
_COMMON_ITEMS: tuple[RubricItem, ...] = (
    RubricItem("output_format", "출력 형식", 5, "|출력 형식|"),
    RubricItem("time_format", "시간 형식", 5, "|시간 형식|"),
    RubricItem("window", "Window 준수", 5, "|Window 준수|"),
    RubricItem("source_match", "Source 일치", 5, "|Source 일치|"),
)


def _event_stage(
    key: str,
    label: str,
    section: str,
    items: tuple[RubricItem, ...],
) -> StageSpec:
    """Event Agent 하나. 공통 기준 20점 + 해당 source 기준 80점."""
    return StageSpec(
        key=key,
        label=label,
        trace_name=TIMELINE_TRACE,
        doc_intro=("1",),
        doc_sections=("1.1", section),
        items=_COMMON_ITEMS + items,
    )


STAGES: tuple[StageSpec, ...] = (
    _event_stage(
        "event-location",
        "Location Event Agent",
        "1.2",
        (
            RubricItem("movement_flow", "이동 흐름", 20, "#### 이동 흐름 — 20점"),
            RubricItem("stay_merge", "체류 병합과 제외", 15, "#### 체류 병합과 제외 — 15점"),
            RubricItem("transport_walk", "이동수단과 산책 추론", 10, "#### 이동수단과 산책 추론 — 10점"),
            RubricItem("place_activity", "장소·주소와 활동 추론", 15, "#### 장소·주소와 활동 추론 — 15점"),
            RubricItem("title_description", "제목·설명·불확실성", 10, "#### 제목·설명·불확실성 — 10점"),
            RubricItem("source_accounting", "Source 전체 처리", 10, "#### Source 전체 처리 — 10점"),
        ),
    ),
    _event_stage(
        "event-calendar",
        "Calendar Event Agent",
        "1.3",
        (
            RubricItem("schedule_coverage", "일정 반영", 20, "모든 Calendar rawId를 candidate·fragment에 포함했는가?"),
            RubricItem("title_time", "제목과 시간", 15, "Calendar title과 startAt·endAt을 candidate·fragment에 동일한 값으로 보존했는가?"),
            RubricItem("event_type_tags", "EventType과 의미 태그", 20, "event의 활동을 적절한 EventType 정의와 대조하고"),
            RubricItem("place", "장소", 10, "locationText를 places에 반영하고 URL을 장소로 사용하지 않았는가?"),
            RubricItem("all_day", "종일 일정", 10, "all-day flag를 보존하고"),
            RubricItem("required_fields", "필수 필드", 5, "각 일정에 title·startAt·endAt·rawId를 포함하고"),
        ),
    ),
    _event_stage(
        "event-notification",
        "Notification Event Agent",
        "1.4",
        (
            RubricItem("type_judgement", "알림 정보 유형 판단", 15, "#### 알림 정보 유형 판단 — 15점"),
            RubricItem("messenger", "메신저", 20, "#### 메신저 — 20점"),
            RubricItem("payment", "결제·송금", 15, "#### 결제·송금 — 15점"),
            RubricItem("reservation", "예약", 15, "#### 예약 — 15점"),
            RubricItem("noise_privacy", "Noise와 개인정보", 10, "#### Noise와 개인정보 — 10점"),
            RubricItem("source_preservation", "Source 보존", 5, "#### Source 보존 — 5점"),
        ),
    ),
    _event_stage(
        "event-photo",
        "Photo Event Agent",
        "1.5",
        (
            RubricItem("photo_description", "사진 묘사", 25, "vision 결과에 장소 유형·피사체·상황 단서"),
            RubricItem("beyond_vision", "Vision 결과 밖 주장", 15, "이미지에서 확인되지 않는 사람·장소·행동·감정·목적을 추가하지 않았는가?"),
            RubricItem("photo_coverage", "사진 반영", 20, "rawId와 촬영 시각을 읽었고"),
            RubricItem("cluster_merge", "사진 cluster 병합", 15, "description 이 유사하고 촬영 시간 차이가 10분 이하인 사진을 같은 candidate로 묶었는가?"),
            RubricItem("source_preservation", "Source 보존", 5, "묶인 사진의 모든 rawId를 보존했는가?"),
        ),
    ),
    StageSpec(
        key="timeline",
        label="Timeline Agent",
        trace_name=TIMELINE_TRACE,
        doc_intro=(),
        doc_sections=("2",),
        items=(
            RubricItem("title_description", "Event의 제목과 Description", 15, "### 2.1 Event의 제목과 Description — 15점"),
            RubricItem("day_flow", "하루 흐름과 필수 반영 사건", 15, "### 2.2 하루 흐름과 필수 반영 사건 — 15점"),
            RubricItem("event_merge", "Candidate·Fragment 병합", 25, "### 2.3 Candidate와 Fragment 를 통한 이벤트 병합 — 25점"),
            RubricItem("source_final", "Source별 최종 반영", 12, "### 2.6 Source별 최종 반영 — 12점"),
            RubricItem("event_type", "EventType", 8, "### 2.5 EventType — 8점"),
            RubricItem("time", "시간", 8, "### 2.7 시간 — 8점"),
            RubricItem("place", "장소와 주소", 5, "### 2.8 장소와 주소 — 5점"),
            RubricItem("confidence", "Confidence와 InferenceLevel", 2, "### 2.9 Confidence와 InferenceLevel — 2점"),
            RubricItem("warnings_memory", "Warnings와 User Memory", 10, "### 2.10 Warnings와 User Memory — 10점"),
        ),
    ),
    StageSpec(
        key="repair",
        label="Repair Agent",
        trace_name=TIMELINE_TRACE,
        doc_intro=(),
        doc_sections=("3",),
        items=(
            RubricItem("input_evidence", "입력과 근거 이해", 15, "### 3.1 입력과 근거 이해 — 15점"),
            RubricItem("issue_detection", "문제 발견", 25, "### 3.2 문제 발견 — 25점"),
            RubricItem("source_type_defects", "Source 유형별 문제 수정", 15, "### 3.3 Source 유형별 문제 수정 — 15점"),
            RubricItem("tool_selection", "Tool 선택과 실행 결과", 20, "### 3.4 Tool 선택과 실행 결과 — 20점"),
            RubricItem("unrelated_edits", "관계없는 수정과 문제 수 변화", 20, "### 3.5 관계없는 수정과 문제 수 변화 — 20점"),
            RubricItem("done_summary", "완료 상태와 Summary", 5, "### 3.6 완료 상태와 Summary — 5점"),
        ),
    ),
    StageSpec(
        key="question",
        label="Question Agent",
        trace_name=TIMELINE_TRACE,
        doc_intro=(),
        doc_sections=("4",),
        items=(
            RubricItem("event_grounding", "Event 이해와 근거", 20, "### 4.1 Event 이해와 근거 — 20점"),
            RubricItem("reflection", "회고 유도 조건", 30, "### 4.2 회고 유도 조건 — 30점"),
            RubricItem("expression", "질문 표현", 20, "### 4.3 질문 표현 — 20점"),
            RubricItem("coverage", "모든 Event의 질문 생성", 20, "### 4.4 모든 Event의 질문 생성 — 20점"),
            RubricItem("uniqueness", "질문 고유성과 연결", 10, "### 4.5 질문 고유성과 연결 — 10점"),
        ),
    ),
    StageSpec(
        key="user-memory",
        label="User Memory Agent",
        trace_name=USER_MEMORY_TRACE,
        doc_intro=(),
        doc_sections=("5",),
        items=(
            RubricItem("provenance", "입력 근거 구분", 20, "### 5.1 입력 근거 구분 — 20점"),
            RubricItem("update_method", "전체 갱신 방식", 15, "### 5.2 전체 갱신 방식 — 15점"),
            RubricItem("field_placement", "근거 일치와 Field 배치", 30, "### 5.3 근거 일치와 Field 배치 — 30점"),
            RubricItem("field_confusion", "Field 혼동과 customAttributes", 15, "### 5.4 Field 혼동과 customAttributes — 15점"),
            RubricItem("size_privacy", "크기·압축·개인정보", 20, "### 5.5 크기·압축·개인정보 — 20점"),
        ),
    ),
)

STAGE_KEYS: tuple[str, ...] = tuple(spec.key for spec in STAGES)
_BY_KEY: dict[str, StageSpec] = {spec.key: spec for spec in STAGES}

TOTAL_POINTS = 100
"""평가 대상 하나의 만점. 문서 규칙."""


def base(key: str) -> StageSpec:
    """메트릭 문서 그대로의 단계 정의(편집본 무시). 설정 화면의 '되돌리기'가 쓴다."""
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"알 수 없는 평가 대상: {key}") from exc


def get(key: str) -> StageSpec:
    """단계 하나. 설정 화면에서 고친 항목이 있으면 **그것이 현재 채점 기준**이다.

    채점 프롬프트·결과 스키마·총점 계산이 모두 이 결과를 쓰므로, 항목을 고치면 다음 채점부터
    바로 반영된다.
    """
    spec = base(key)
    edited = rubric_store.load(key)
    if not edited:
        return spec
    return replace(
        spec,
        items=tuple(
            # 편집본은 문서에서 찾을 필요가 없으므로 marker 를 비운다(→ criteria 가 저장본을 쓴다).
            RubricItem(row["key"], row["label"], int(row["points"]), "")
            for row in edited
        ),
    )


def is_edited(key: str) -> bool:
    """설정 화면에서 고친 기준을 쓰고 있는지."""
    return rubric_store.is_edited(key)


def for_trace(trace_name: str | None) -> tuple[StageSpec, ...]:
    """그 트레이스에서 채점할 수 있는 단계들."""
    return tuple(spec for spec in STAGES if spec.trace_name == trace_name)


@dataclass(frozen=True)
class ItemCriteria:
    """항목 하나의 확인 기준(문서 원문). 표로 보여줄 때도, 프롬프트에 넣을 때도 이걸 쓴다."""

    item: RubricItem
    llm: str
    """`LLM 확인` — 의미를 대조해 판단할 기준."""
    code: str
    """`코드 측정` — 문서에는 있지만 채점에는 쓰지 않는다. 확인 기준과 섞이지 않게 갈라만 둔다."""
    body: str
    """블록 원문 전체(항목 안에 있는 표까지 포함)."""

    @property
    def text(self) -> str:
        """화면에 보여줄 확인 기준. `LLM 확인` 이 있으면 그것, 없으면 원문 전체."""
        return self.llm or self.body


_CRITERIA_LABELS = ("LLM 확인", "코드 측정")


def _split_criteria(body: str) -> tuple[str, str]:
    """블록 본문을 `LLM 확인` / `코드 측정` 두 덩어리로 나눈다.

    라벨 뒤 콜론은 있을 수도 없을 수도 있다. 라벨 앞에 있는 문장·표는 확인 기준으로 본다
    (예: 5.3 은 `LLM 확인` 라벨 없이 설명 문장과 고정 field 표로 기준을 적는다).
    """
    buckets: dict[str, list[str]] = {label: [] for label in _CRITERIA_LABELS}
    current = _CRITERIA_LABELS[0]
    for line in body.splitlines():
        stripped = line.strip()
        matched = next((label for label in _CRITERIA_LABELS if stripped.rstrip(":") == label), None)
        if matched is not None:
            current = matched
            continue
        buckets[current].append(line)
    return (
        "\n".join(buckets["LLM 확인"]).strip(),
        "\n".join(buckets["코드 측정"]).strip(),
    )


def criteria(spec: StageSpec) -> tuple[ItemCriteria, ...]:
    """항목마다 문서에서 확인 기준을 잘라 붙인다. 배점표의 순서를 유지한다.

    설정 화면에서 고친 단계는 저장본을 그대로 쓴다. 그렇지 않으면 문서에서 자른다. 문서의 항목은
    두 형태다. `#### 이동 흐름 — 20점` 같은 heading 블록이거나, 표 한 줄
    (`|측정 기준|LLM 확인|코드 측정|배점|`)이다. 둘 다 같은 모양으로 만든다.
    """
    edited = rubric_store.load(spec.key)
    if edited:
        stored = {row["key"]: row["criteria"] for row in edited}
        return tuple(
            ItemCriteria(item, stored.get(item.key, ""), "", stored.get(item.key, ""))
            for item in spec.items
        )

    text = "\n\n".join(metric_doc.section(number) for number in spec.doc_sections)
    _, blocks = metric_doc.split_by_markers(text, [item.marker for item in spec.items])

    out: list[ItemCriteria] = []
    for item in spec.items:
        body = blocks[item.marker]
        cells = metric_doc.table_row_cells(body.splitlines()[0])
        if len(cells) >= 3:
            # 표 한 줄: |측정 기준|LLM 확인|코드 측정|배점|. 칸이 비면 기준도 비어야 검사에 걸린다.
            out.append(ItemCriteria(item, cells[1], cells[2], cells[1]))
            continue
        body_without_heading = "\n".join(body.splitlines()[1:]).strip()
        llm, code = _split_criteria(body_without_heading)
        out.append(ItemCriteria(item, llm, code, body_without_heading))
    return tuple(out)


def criteria_text(spec: StageSpec) -> str:
    """채점 항목 본문. 항목마다 키·배점·확인 기준이 한 덩어리로 붙는다.

    배점표를 따로 두지 않는다. 배점이 항목 제목에 있어서 표를 하나 더 두면 같은 내용을 두 번 읽게
    된다. 문서의 `코드 측정` 은 채점에 쓰지 않으므로 넣지 않는다.
    """
    blocks = [
        f"## 채점 항목 — {spec.label} (항목 {len(spec.items)}개 · 합계 {spec.total_points}점)",
        "항목마다 아래 확인 기준을 그대로 적용해 점수와 이유를 남긴다. **항목을 하나도 빠뜨리지 "
        "않는다.** 만점이어도 무엇을 확인해 문제가 없었는지 이유에 적는다.",
    ]
    for entry in criteria(spec):
        item = entry.item
        blocks.append(f"### `{item.key}` · {item.label} — 배점 {item.points}점")
        blocks.append(entry.text)
    return "\n\n".join(block.strip() for block in blocks if block.strip())


# 문서의 `코드 측정` 은 채점에 쓰지 않는다(코드가 계산하지 않으니 채점자가 눈대중으로 센 숫자가
# 된다). 공통 머리말에서 그 정의와 사용 규칙 두 줄만 덜어낸다.
_CODE_METRIC_LINES = ("- `코드 측정`:", "- 코드 측정값이 제공되면")


def _without_code_metric(text: str) -> str:
    return "\n".join(
        line
        for line in text.splitlines()
        if not any(line.startswith(prefix) for prefix in _CODE_METRIC_LINES)
    )


def rubric_text(spec: StageSpec) -> str:
    """단계 하나의 채점 기준 전문(공통 규칙 + 채점 항목).

    문서 6장(점수 작성 형식)은 넣지 않는다. 결과는 JSON 스키마로 받고 총점은 코드가 계산하므로
    텍스트 출력 형식을 지시하면 오히려 어긋난다. 6장의 규칙(항목 합 = 총점, 감점 근거에 rawId·출력
    위치)은 채점자 지시에 이미 들어 있다.
    """
    blocks = [_without_code_metric(metric_doc.preamble())]
    blocks.extend(metric_doc.intro(number) for number in spec.doc_intro)
    blocks.append(criteria_text(spec))
    return "\n\n".join(block.strip() for block in blocks if block.strip())


def validate(spec: StageSpec | None = None) -> None:
    """배점 합계와 **문서 항목 누락**을 검사한다. 어긋나면 로딩 자체를 실패시킨다.

    조용히 일부 항목만 프롬프트에 들어가는 상태를 막는 장치다. 문서에서 항목을 지우거나 배점을
    바꾸면 여기서 걸리고, 그때 이 모듈의 표를 같이 고치게 된다.
    """
    targets = STAGES if spec is None else (spec,)
    for target in targets:
        if target.total_points != TOTAL_POINTS:
            raise ValueError(
                f"{target.key} 배점 합계가 {target.total_points}점입니다(문서 기준 {TOTAL_POINTS}점)."
            )
        keys = [item.key for item in target.items]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{target.key} 항목 키가 중복됩니다: {keys}")
        try:
            entries = criteria(target)
        except metric_doc.MetricDocumentError as exc:
            raise ValueError(f"{target.key} 채점 기준을 문서에서 만들지 못했습니다: {exc}") from exc
        empty = [entry.item.key for entry in entries if not entry.text.strip()]
        if empty:
            raise ValueError(
                f"{target.key} 의 다음 항목에 확인 기준이 비어 있습니다(문서를 확인하세요): {empty}"
            )
