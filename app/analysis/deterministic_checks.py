"""형식이 확인된 질문 입력·출력에만 적용하는 결정론 검사."""

from __future__ import annotations

from collections import Counter

from app.analysis import stages
from app.analysis.evidence import StageEvidence, parse_json_array


def confirmed_checks(evidence: StageEvidence) -> dict:
    """읽을 수 없는 자료는 측정값을 만들지 않는다. 편집본은 다른 규칙일 수 있어 제외한다."""
    if evidence.key != "question" or stages.is_edited(evidence.key):
        return {}
    sections = {section.title: section.payload for section in evidence.sections}
    inputs = parse_json_array(sections.get("입력 event"))
    outputs = parse_json_array(sections.get("출력 질문"))
    if inputs is None or outputs is None:
        return {}
    ids = [row.get("clientEventId") for row in inputs]
    if any(not isinstance(key, str) or not key.strip() for key in ids) or len(set(ids)) != len(ids):
        return {}
    if any(not isinstance(row.get("clientEventId"), str) for row in outputs):
        return {}
    counts = Counter(row["clientEventId"] for row in outputs if isinstance(row.get("question"), str) and row["question"].strip())
    failed = [key for key in ids if counts[key] != 1]
    coverage = {
        "total": len(ids), "passed": len(ids) - len(failed), "failedRefs": failed,
        "reason": f"코드 확인: 입력 ID {len(ids)}개 중 질문이 정확히 1개인 ID {len(ids)-len(failed)}개. 유형별로도 동일 입력 ID를 대조함.",
    }
    lengths = [len(row["question"].strip()) if isinstance(row.get("question"), str) else 0 for row in outputs]
    failed_lengths = [f"questions[{i}].question" for i, length in enumerate(lengths) if not 1 <= length <= 40]
    present = {row["clientEventId"] for row in outputs}
    missing = [key for key in ids if key not in present]
    failed_lengths.extend(f"missing:{key}.question" for key in missing)
    length_total = len(outputs) + len(missing)
    return {
        "coverage": {"c01": coverage, "c02": dict(coverage)},
        "expression": {"c02": {
            "total": length_total, "passed": length_total - len(failed_lengths), "failedRefs": failed_lengths,
            "reason": "코드 확인: 앞뒤 공백 제거 후 Unicode 문자 수 1~40자. 빈 질문·누락은 실패. "
                      f"출력별 글자 수={lengths}, 누락={len(missing)}개.",
        }},
    }
