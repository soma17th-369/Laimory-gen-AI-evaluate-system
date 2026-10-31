"""합성 보류 사례로 기존/개선 채점 반복 비교. 운영 평가 파일은 갱신하지 않는다.

실행: .venv/Scripts/python.exe scripts/check_judge_repeatability.py --model <현재 모델> --repeats 5
결과는 data/validation/<실행 시각>/에 저장한다. 실제 LLM 호출이 발생한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis import stage_judge, stage_schema, stages
from app.analysis.evidence import EvidenceSection, StageEvidence, build_user_prompt
from app.analysis.providers import CodexProvider
from app.prompts import registry
from app.storage import store


def fixtures():
    events = [
        {"clientEventId": "E1", "title": "박물관 관람", "description": "박물관 전시를 관람했어요.", "place": "박물관", "timeOfDay": "오후", "eventType": "UNKNOWN"},
        {"clientEventId": "E2", "title": "체육관 운동", "description": "체육관에서 운동했어요.", "place": "체육관", "timeOfDay": "저녁", "eventType": "EXERCISE"},
        {"clientEventId": "E3", "title": "점심 식사", "description": "식당에서 점심을 먹었어요.", "place": "식당", "timeOfDay": "점심 무렵", "eventType": "MEAL"},
        {"clientEventId": "E4", "title": "도서관 독서", "description": "도서관에서 책을 읽었어요.", "place": "도서관", "timeOfDay": "아침", "eventType": "UNKNOWN"},
    ]
    good = [
        {"clientEventId": "E1", "question": "박물관 전시에서 무엇이 가장 기억에 남았나요?"},
        {"clientEventId": "E2", "question": "체육관 운동에서 어떤 점을 새롭게 배웠나요?"},
        {"clientEventId": "E3", "question": "점심 식사에서 어떤 맛이 가장 인상 깊었나요?"},
        {"clientEventId": "E4", "question": "도서관에서 읽은 책은 어떤 생각을 하게 했나요?"},
    ]
    flawed = [dict(row) for row in good[:3]]
    flawed[1]["question"] = "동생과 체육관에서 운동하며 어떤 기분이 들었나요?"
    for name, output in (("heldout-good", good), ("heldout-missing-and-unsupported", flawed)):
        yield name, StageEvidence(stages.get("question"), True, sections=(
            EvidenceSection("입력 event", "실제 사실 전체. 동행 인물에 대한 추가 근거는 없다.", events),
            EvidenceSection("입력 User Memory", "보조 정보 없음", "정보 없음"),
            EvidenceSection("출력 질문", "평가할 최종 출력 전체", output),
        ))


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats는 1 이상이어야 합니다")
    baseline = registry.get("judge-stage-question", 2)
    if not baseline:
        raise SystemExit("기존 judge-stage-question v2 원문이 없어 비교를 중단합니다")
    new_prompt = stage_judge.system_prompt("question")
    provider = CodexProvider(model=args.model)
    output_dir = Path("data/validation") / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=False)
    cases = dict(fixtures())
    store.save_json(output_dir / "setup.json", {
        "model": args.model, "repeats": args.repeats, "stage": "question",
        "baselineVersion": 2, "baselinePrompt": baseline["content"], "newPrompt": new_prompt,
        "inputs": {name: build_user_prompt(ev) for name, ev in cases.items()},
        "promptHashes": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in (("old", baseline["content"]), ("new", new_prompt))},
        "expectedCoverage": {"heldout-good": 20, "heldout-missing-and-unsupported": 15},
        "expectedUnsupportedRef": {"heldout-good": None, "heldout-missing-and-unsupported": "E2"},
        "limitation": "합성 보류 사례 2개. 전체 점수의 사람 확정 정답은 없으며 실제 사용자 데이터 분포를 대표하지 않음.",
    })

    def judge(name, variant, iteration):
        ev = cases[name]
        try:
            if variant == "new":
                result = stage_judge.score_evidence(ev, system_prompt_text=new_prompt)
            else:
                card = provider.evaluate(system_prompt=baseline["content"], user_prompt=build_user_prompt(ev), result_model=stage_schema.scorecard_model("question"))
                result = stage_schema.tally(ev.stage, card)
            entry = {"case": name, "variant": variant, "iteration": iteration, "scorecard": result.to_dict()}
        except Exception as exc:
            entry = {"case": name, "variant": variant, "iteration": iteration, "error": f"{type(exc).__name__}: {exc}"}
        store.save_json(output_dir / f"{name}-{variant}-{iteration}.json", entry)
        return entry

    results = []
    with patch.object(stage_judge, "get_llm_provider", return_value=provider), ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(judge, name, variant, iteration) for iteration in range(1, args.repeats+1) for name in cases for variant in ("old", "new")]
        for job in as_completed(jobs):
            entry = job.result()
            results.append(entry)
            print(json.dumps({key: entry[key] for key in ("case", "variant", "iteration")} | {"total": entry.get("scorecard", {}).get("total"), "error": entry.get("error")}, ensure_ascii=False), flush=True)
    summary = []
    for name in cases:
        for variant in ("old", "new"):
            entries = [row for row in results if row["case"] == name and row["variant"] == variant]
            cards = [row["scorecard"] for row in entries if "scorecard" in row]
            totals = [row["total"] for row in cards if row["total"] is not None]
            item_scores = {item.key: [next(x["score"] for x in card["items"] if x["key"] == item.key) for card in cards] for item in stages.get("question").items}
            summary.append({"case": name, "variant": variant, "successes": len(cards), "failures": len(entries)-len(cards),
                            "totals": totals, "range": max(totals)-min(totals) if totals else None,
                            "stddev": statistics.pstdev(totals) if totals else None, "itemScores": item_scores,
                            "naCounts": [len(card["redistributed"]) for card in cards]})
    store.save_json(output_dir / "summary.json", {"model": args.model, "summary": summary})
    print(f"RESULT_DIR={output_dir.resolve()}", flush=True)


if __name__ == "__main__":
    run()
