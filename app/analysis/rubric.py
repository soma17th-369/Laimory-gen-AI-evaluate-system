"""채점 rubric 프롬프트 (M2).

judge 에 주는 시스템 프롬프트와 근거 조립. 프롬프트를 크게 바꿀 때는 이 파일에서 관리한다.
채점은 **오직 주어진 근거**(입력 스냅샷·최종 출력)에만 기반한다 — 근거에 없는 것은 감점 사유.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """\
당신은 생성형 AI 가 만든 '하루 타임라인'의 품질을 평가하는 엄정한 채점자다.
대상 AI 는 사용자의 하루 수집 데이터(위치·캘린더·건강·사진·알림 등)를 받아, 하루를
event 들의 타임라인으로 만들고 각 event 에 회고 질문을 붙인다.

너는 아래 7개 기준으로 **최종 출력**을 평가한다. 각 기준은 0~10 정수로 매긴다
(0=심각한 위반, 10=문제 없음). overall 은 단순 평균이 아니라 하루 기록으로서의 종합 판단이다.

기준:
1. grounding(근거 충실성/환각): 출력이 입력 근거에 기반하는가. 지어낸 사건·장소·시간이 없는가.
2. temporal(시간 정합성): event 시각·순서가 요청 기간(window)·수면 경계·근거 구간과 모순 없는가.
3. place(장소 정합성): 장소/주소가 근거에 있고 잘못 붙지 않았는가.
4. coverage(완결성): 주요 활동·캘린더 일정 누락 없이 하루가 설명되는가.
5. writing(문장 품질): title·description 이 1인칭 해요체 과거형이고, 추정 표현(예: '듯해요')과
   원시 수치(분 단위 시각·걸음 수)를 문장에 쓰지 않으며, 길이가 적정한가.
6. question(회고 질문): 모든 event 에 해요체 의문문·40자 내외의 회고 질문이 하나씩 붙었는가.

채점 규칙:
- 오직 주어진 근거(입력·최종 출력)에만 근거해 판단한다. 근거에 없는 사실을 지어내지 않는다.
- 확신이 없으면 점수를 낮추고 그 이유를 findings 에 남긴다.
- findings 는 구체적 문제만 담는다(criterion 키·심각도·설명). 문제가 없으면 빈 리스트.
- 모든 텍스트(reason·description·summary)는 한국어로 쓴다.
- 반드시 지정된 JSON 스키마 형식으로만 답한다.
"""


def _as_text(value: Any, limit: int = 20000) -> str:
    """근거 값을 프롬프트용 텍스트로. dict/list 는 JSON 직렬화, 과도하면 자른다."""
    if value is None:
        return "(없음)"
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > limit:
        text = text[:limit] + f"\n…(생략: 총 {len(text)}자)"
    return text


_EVENT_FIELD_HINT = (
    "각 event 필드: title·description(사용자 노출 문장), startTime·endTime(시각), "
    "address·placeLabel(장소), question(회고 질문), eventType·confidence·inferenceLevel·"
    "sourceRefs·uncertainty(근거·불확실성)."
)


def build_user_prompt(evidence: dict) -> str:
    """assemble_evidence() 결과를 채점용 사용자 메시지로 조립한다."""
    obs = evidence.get("observations") or []
    obs_lines = "\n".join(f"- [{o.get('type')}] {o.get('name')}" for o in obs) or "(없음)"
    return (
        f"트레이스 이름: {evidence.get('name')}\n\n"
        f"[입력 근거 — 수집 스냅샷]\n{evidence.get('input')}\n\n"
        f"[최종 출력 — 타임라인 events · 출처: {evidence.get('output_source')}]\n"
        f"{_EVENT_FIELD_HINT}\n{evidence.get('output')}\n\n"
        f"[관측치 목록(참고)]\n{obs_lines}\n\n"
        "위 근거로 7개 기준을 채점하고 문제점을 정리하라. "
        "채점 대상은 최종 타임라인 events 이고, 입력 스냅샷은 근거 대조용이다."
    )
