"""테스트 케이스 생성 (M4b).

리포트 문제점을 재현·검증하는 {입력 + 기대 조건} 케이스를 만든다. 공통 LLM provider를 쓰고,
결과는 json 으로 내보낼 수 있다(단순화 입력 스키마).
"""

from __future__ import annotations

from app.analysis import evaluation_record
from app.analysis.providers import get_llm_provider
from app.testdata.schema import TestSuite

_SYSTEM_PROMPT = """\
당신은 생성형 AI '하루 타임라인' 파이프라인의 QA 엔지니어다.
채점 문제점을 받아, 그 문제를 **재현하고 검증**하는 테스트 케이스를 만든다.

각 케이스는:
- input: 하루 수집 데이터(stays·movements·calendars·notifications). 문제를 좁혀 재현하는 **최소한**의
  현실적인 입력. 시각은 ISO8601, 서로 모순 없게.
- expected: 그 입력으로 타임라인을 만들면 **무엇이 참이어야 하는지**('이런 event 가 나와야'
  또는 '나오면 안 됨'). 기준(temporal/place/…)에 대응하는 검증 조건.

규칙:
- 문제점 하나당 하나 이상 케이스. 각 케이스는 targets_criteria 로 검증 기준(평가 대상·항목 키)을 밝힌다.
- 실제 개인정보/실명/실주소를 쓰지 않는다(가상의 값).
- 모든 텍스트는 한국어. 지정된 JSON 스키마로만 답한다.
"""


def generate_test_cases(record: dict) -> TestSuite:
    """단계별 채점의 감점 근거 → 재현·검증 테스트 스위트."""
    user = (
        "[채점 문제점 — 평가 대상별]\n"
        f"{evaluation_record.findings_text(record)}\n\n"
        "위 문제를 재현·검증하는 테스트 케이스(입력 + 기대 조건)를 만들어라."
    )
    return get_llm_provider().generate_structured(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user,
        result_model=TestSuite,
    )


def testsuite_to_json(suite: TestSuite) -> str:
    import json

    return json.dumps(suite.model_dump(), ensure_ascii=False, indent=2)
