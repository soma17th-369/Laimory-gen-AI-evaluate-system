"""테스트 케이스 생성 (M4b).

리포트 문제점을 재현·검증하는 {입력 + 기대 조건} 케이스를 만든다. judge 와 같은 OpenAI
클라이언트·모델을 쓰고, 결과는 json 으로 내보낼 수 있다(단순화 입력 스키마).
"""

from __future__ import annotations

from app.analysis.judge import get_openai_client
from app.analysis.schema import CRITERION_LABELS, TraceScorecard
from app.config import get_settings
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
- 문제점 하나당 하나 이상 케이스. 각 케이스는 targets_criteria 로 검증 기준을 밝힌다.
- 실제 개인정보/실명/실주소를 쓰지 않는다(가상의 값).
- 모든 텍스트는 한국어. 지정된 JSON 스키마로만 답한다.
"""


def _findings_text(scorecard: TraceScorecard) -> str:
    lines = [f"- 종합 {scorecard.overall.score}/10: {scorecard.summary}"]
    for finding in scorecard.findings:
        label = CRITERION_LABELS.get(finding.criterion, finding.criterion)
        lines.append(f"- [{finding.severity}] ({label}) {finding.description}")
    return "\n".join(lines)


def generate_test_cases(scorecard: TraceScorecard) -> TestSuite:
    """채점 문제점 → 재현·검증 테스트 스위트."""
    user = (
        "[채점 문제점]\n"
        f"{_findings_text(scorecard)}\n\n"
        "위 문제를 재현·검증하는 테스트 케이스(입력 + 기대 조건)를 만들어라."
    )
    client = get_openai_client()
    model = get_settings().openai_judge_model

    def _parse(**extra):
        return client.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user}],
            response_format=TestSuite,
            **extra,
        )

    try:
        completion = _parse(temperature=0)
    except Exception as exc:  # noqa: BLE001
        if "temperature" in str(exc).lower():
            completion = _parse()
        else:
            raise

    suite = completion.choices[0].message.parsed
    if suite is None:
        raise RuntimeError("모델이 구조화 결과를 반환하지 않았습니다.")
    return suite


def testsuite_to_json(suite: TestSuite) -> str:
    import json

    return json.dumps(suite.model_dump(), ensure_ascii=False, indent=2)
