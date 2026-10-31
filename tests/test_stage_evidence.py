"""trace.json v2 정규화와 단계별 근거 슬라이서.

실 로그 본문은 저장소에 두지 않으므로(→ AGENT.md) 관측치 모양만 흉내 낸 합성 트레이스를 쓴다.
확인하는 것: 단계마다 **자기 입력만** 들어가는가, 중복이 blob 으로 접히는가, 근거가 없을 때
0점이 아니라 N/A 로 떨어지는가.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.analysis import evidence
from app.tasks.trace_builder import build_trace_json, resolve

_WINDOW = {"start": "2026-09-04T00:00:00+09:00", "end": "2026-09-05T00:00:00+09:00"}
_DRAFT = {"events": [{"clientEventId": "event-001", "title": "초안"}], "warnings": []}
_REPAIRED = {"events": [{"clientEventId": "event-001", "title": "고친 뒤"}], "warnings": []}
_WITH_QUESTION = {
    "events": [{"clientEventId": "event-001", "title": "고친 뒤", "question": "어떤 하루였나요?"}],
    "questions": [],
    "warnings": [],
}

_REQUEST = {
    "taskId": "01a0413d-1e34-7785-b1dc-5e8bc5321f02",
    "date": "2026-09-04",
    "timezone": "Asia/Seoul",
    "window": _WINDOW,
    "userMemory": {"contentCaptured": False, "byteLength": 116, "filledFieldCount": 1},
    "stays": [{"rawId": "stay-1", "place": "집"}],
    "movements": [{"rawId": "move-1", "start": "집", "end": "회사"}],
    "calendars": [],
    "notifications": [{"rawId": "noti-1", "appName": "카카오톡", "text": "안녕"}],
    "photos": [{"rawId": "photo-1", "takenAt": "2026-09-04T12:06:24+09:00", "description": None}],
    "healths": [],
}


def _obs(name, obs_type, *, parent=None, obs_id=None, metadata=None, inp=None, out=None, level="DEFAULT"):
    return SimpleNamespace(
        id=obs_id or name,
        name=name,
        type=obs_type,
        parent_observation_id=parent,
        metadata=metadata or {},
        input=inp,
        output=out,
        level=level,
        status_message=None,
        start_time=None,
        end_time=None,
        model="gpt-5.4-mini",
        usage=None,
        usage_details={},
    )


def _timeline_trace() -> SimpleNamespace:
    """`generate-timeline` 한 건. 캘린더·건강은 0건이라 그 단계는 채점 대상이 아니다."""
    agents = []
    for agent, result in (
        ("location", {"candidates": [{"title": "출근"}], "fragments": [], "warnings": []}),
        ("calendar", {"candidates": [], "fragments": [], "warnings": []}),
        ("photo", {"candidates": [{"title": "점심"}], "fragments": [], "warnings": []}),
        ("notification", {"candidates": [], "fragments": [{"rawId": "noti-1"}], "warnings": []}),
    ):
        agents.append(
            _obs(
                f"event-agent-{agent}",
                "AGENT",
                parent="main-agent",
                metadata={"agent": agent, "sourceStage": "event"},
                inp={"request": _REQUEST, "taskId": "t", "hasUserMemory": True},
                out={"result": result, "tokenUsage": {}},
            )
        )
    observations = [
        _obs("main-agent", "AGENT", inp={"request": _REQUEST}, out={"timeline": _WITH_QUESTION}),
        *agents,
        _obs(
            "describe-photo-images",
            "GENERATION",
            parent="event-agent-photo",
            metadata={"imageCount": 1},
            inp=[{"role": "system", "content": "사진 묘사"}],
            out=[{"role": "assistant", "content": '{"descriptions":[{"rawId":"photo-1","description":"햄버거"}]}'}],
        ),
        _obs(
            "merge-event-results",
            "CHAIN",
            parent="main-agent",
            out={"mergedResult": {"candidates": [{"title": "출근"}], "fragments": [{"rawId": "noti-1"}], "warnings": []}},
        ),
        _obs(
            "timeline-agent",
            "AGENT",
            parent="main-agent",
            metadata={"agent": "timeline"},
            inp={"request": _REQUEST, "mergedResult": {"candidates": []}},
            out={"timeline": _DRAFT},
        ),
        _obs(
            "generate-timeline-draft",
            "GENERATION",
            parent="timeline-agent",
            inp=[
                {"role": "system", "content": "타임라인 지시"},
                {"role": "user", "content": "[draft metadata]\n2026-09-04\n\n[user memory]\n혼자 사는 개발자\n\n[AI Event candidates]\n[]"},
            ],
            out=[{"role": "assistant", "content": "{}"}],
        ),
        _obs(
            "repair-agent",
            "AGENT",
            parent="main-agent",
            metadata={"agent": "repair", "maxIterations": 3},
            inp={"request": _REQUEST, "timeline": _DRAFT},
            out={"timeline": _REPAIRED},
        ),
        _obs(
            "analyze-repair-iteration",
            "CHAIN",
            obs_id="analyze-1",
            parent="repair-agent",
            metadata={"iteration": 1},
            out={"plan": {"issues": [{"clientEventId": "event-001", "problem": "제목이 밋밋"}], "toolCalls": [{"tool": "update_event"}], "done": False}},
        ),
        _obs(
            "execute-repair-plan",
            "CHAIN",
            obs_id="execute-plan-1",
            parent="repair-agent",
            metadata={"iteration": 1},
            out={"results": [{"tool": "update_event", "ok": True, "message": "고쳤습니다"}]},
        ),
        _obs(
            "execute-update-event",
            "SPAN",
            obs_id="tool-1",
            parent="execute-plan-1",
            metadata={"tool": "update_event"},
            inp={"call": {"tool": "update_event", "args": {"clientEventId": "event-001"}, "reason": "제목"}, "timeline": _DRAFT},
            out={"ok": True, "result": {"tool": "update_event", "ok": True}, "timeline": _REPAIRED},
        ),
        _obs(
            "confirm-repair-iteration",
            "CHAIN",
            parent="repair-agent",
            metadata={"iteration": 1},
            out={"timeline": _REPAIRED},
        ),
        _obs(
            "question-agent",
            "AGENT",
            parent="main-agent",
            metadata={"agent": "question"},
            inp={"date": "2026-09-04", "timeline": _REPAIRED},
            out={"timeline": _WITH_QUESTION},
        ),
        _obs(
            "generate-event-questions",
            "GENERATION",
            parent="question-agent",
            inp=[
                {"role": "system", "content": "질문 지시"},
                {"role": "user", "content": '[date]\n2026-09-04\n\n[user memory]\n정보 없음\n\n[events]\n[{"clientEventId": "event-001", "timeOfDay": "오후"}]'},
            ],
            out=[{"role": "assistant", "content": '{"questions":[{"clientEventId":"event-001","question":"어떤 하루였나요?"}]}'}],
        ),
    ]
    return SimpleNamespace(
        id="trace-1",
        name="generate-timeline",
        session_id="01a0413d-1e34-7785-b1dc-5e8bc5321f02",
        tags=["timeline"],
        timestamp=None,
        input={"taskId": _REQUEST["taskId"], "dailyRecordId": 1, "window": _WINDOW, "request": _REQUEST},
        output={"status": "SUCCESS", "timeline": _WITH_QUESTION},
        observations=observations,
    )


def _user_memory_trace() -> SimpleNamespace:
    return SimpleNamespace(
        id="trace-2",
        name="update-user-memory",
        session_id="t-2",
        tags=["user-memory"],
        timestamp=None,
        input={"taskId": "t-2"},
        output={"status": "SUCCESS", "userMemory": {"contentCaptured": False, "sha256": "…"}},
        observations=[
            _obs("update-user-memory", "SPAN", out={"status": "SUCCESS"}),
            _obs(
                "update-user-memory-profile",
                "GENERATION",
                parent="update-user-memory",
                inp=[
                    {"role": "system", "content": "프로필 지시"},
                    {"role": "user", "content": "[existing user memory]\n정보 없음\n\n[dailyTimelines]\n[{...}]"},
                ],
                out=[{"role": "assistant", "content": '{"basicProfile": "개발자"}'}],
            ),
        ],
    )


class TraceJsonV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.trace_json = build_trace_json(_timeline_trace())

    def test_stage_timelines_are_kept_and_deduplicated(self) -> None:
        steps = {step["name"]: step for step in self.trace_json["process"]["steps"]}
        draft = resolve(self.trace_json, steps["timeline-agent"]["timelineRef"])
        repaired = resolve(self.trace_json, steps["repair-agent"]["timelineRef"])

        self.assertEqual(draft, _DRAFT)
        self.assertEqual(repaired, _REPAIRED)
        # 같은 내용이면 같은 blob 을 가리킨다(반복되는 타임라인 스냅샷이 파일을 부풀리지 않는다).
        self.assertEqual(
            steps["repair-agent"]["timelineRef"], steps["confirm-repair-iteration"]["timelineRef"]
        )
        # 통과 중복은 아예 담지 않는다.
        self.assertIsNone(steps["execute-update-event"]["timelineRef"])

    def test_source_is_not_copied_into_every_step(self) -> None:
        for step in self.trace_json["process"]["steps"]:
            with self.subTest(step=step["name"]):
                self.assertNotIn("request", step["input"] or {})
                self.assertNotIn("mergedResult", step["input"] or {})

    def test_generation_prompts_and_outputs_are_stored(self) -> None:
        generation = next(
            gen for gen in self.trace_json["process"]["generations"] if gen["name"] == "generate-event-questions"
        )
        self.assertIn("questions", str(resolve(self.trace_json, generation["outputRef"])))
        self.assertIn("[events]", str(resolve(self.trace_json, generation["inputRef"])))

    def test_stage_metadata_and_level_survive(self) -> None:
        steps = {step["name"]: step for step in self.trace_json["process"]["steps"]}
        self.assertEqual(steps["timeline-agent"]["metadata"], {"agent": "timeline"})
        self.assertEqual(steps["analyze-repair-iteration"]["metadata"]["iteration"], 1)
        self.assertEqual(steps["main-agent"]["level"], "DEFAULT")

    def test_schema_version_and_trace_identity(self) -> None:
        self.assertEqual(self.trace_json["schemaVersion"], 2)
        self.assertEqual(self.trace_json["task"]["traceName"], "generate-timeline")
        self.assertEqual(self.trace_json["task"]["tags"], ["timeline"])


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trace_json = build_trace_json(_timeline_trace())
        self.evidences = {item.key: item for item in evidence.build_all(self.trace_json)}

    def test_timeline_trace_covers_seven_targets(self) -> None:
        self.assertEqual(len(self.evidences), 7)
        self.assertNotIn("user-memory", self.evidences)

    def test_event_agent_only_sees_its_own_source(self) -> None:
        location = self.evidences["event-location"]
        payload = next(section.payload for section in location.sections if section.title == "입력 source")

        self.assertEqual(set(payload), {"stays", "movements"})
        prompt = evidence.build_user_prompt(location)
        self.assertIn("stay-1", prompt)
        self.assertNotIn("noti-1", prompt)

    def test_empty_source_is_not_scored(self) -> None:
        calendar = self.evidences["event-calendar"]

        self.assertFalse(calendar.applicable)
        self.assertIn("0건", calendar.skip_reason)

    def test_photo_evidence_carries_vision_result(self) -> None:
        photo = self.evidences["event-photo"]
        vision = next(section for section in photo.sections if section.title == "Vision 결과")

        self.assertIn("햄버거", str(vision.payload))

    def test_timeline_evidence_takes_user_memory_from_the_prompt(self) -> None:
        timeline = self.evidences["timeline"]
        memory = next(section for section in timeline.sections if section.title == "입력 User Memory")
        draft = next(section for section in timeline.sections if section.title == "출력 draft timeline")

        self.assertEqual(memory.payload, "혼자 사는 개발자")
        self.assertEqual(draft.payload, _DRAFT)

    def test_repair_evidence_pairs_plans_with_tool_calls(self) -> None:
        repair = self.evidences["repair"]
        iterations = next(
            section.payload for section in repair.sections if section.title == "회차별 계획과 도구 실행"
        )

        self.assertEqual(len(iterations), 1)
        self.assertEqual(iterations[0]["iteration"], 1)
        self.assertEqual(iterations[0]["toolCalls"][0]["tool"], "update_event")
        self.assertEqual(iterations[0]["resultEvents"][0]["clientEventId"], "event-001")
        self.assertEqual(repair.summary["eventsBefore"], 1)

    def test_question_evidence_reads_embedded_questions(self) -> None:
        question = self.evidences["question"]
        questions = next(section.payload for section in question.sections if section.title == "출력 질문")

        self.assertEqual(questions, [{"clientEventId": "event-001", "question": "어떤 하루였나요?"}])
        self.assertEqual(question.summary["questions"], 1)

    def test_older_logs_keep_questions_in_a_separate_array(self) -> None:
        """예전 로그는 events[].question 대신 timeline.questions 를 쓴다."""
        trace = _timeline_trace()
        old_shape = {
            "events": [{"clientEventId": "event-001", "title": "고친 뒤"}],
            "questions": [{"clientEventId": "event-001", "question": "예전 질문인가요?"}],
            "warnings": [],
        }
        for observation in trace.observations:
            if observation.name == "question-agent":
                observation.output = {"timeline": old_shape}

        built = evidence.build(build_trace_json(trace), "question")
        questions = next(section.payload for section in built.sections if section.title == "출력 질문")

        self.assertEqual(questions[0]["question"], "예전 질문인가요?")
        self.assertEqual(built.summary["questions"], 1)

    def test_missing_question_output_with_input_is_still_evaluable(self) -> None:
        trace = _timeline_trace()
        for observation in trace.observations:
            if observation.name == "question-agent":
                observation.output = {"timeline": {"events": [], "questions": []}}
            if observation.name == "generate-event-questions":
                observation.input = [{"role": "user", "content": '[events]\n[{"clientEventId":"event-001"}]'}]
        built = evidence.build(build_trace_json(trace), "question")
        self.assertTrue(built.applicable)
        from app.analysis.deterministic_checks import confirmed_checks
        coverage = confirmed_checks(built)["coverage"]["c01"]
        self.assertEqual((coverage["total"], coverage["passed"]), (1, 0))

    def test_user_memory_comes_from_its_own_trace(self) -> None:
        memory_json = build_trace_json(_user_memory_trace())
        built = {item.key: item for item in evidence.build_all(memory_json)}

        self.assertEqual(list(built), ["user-memory"])
        self.assertTrue(built["user-memory"].applicable)
        profile = next(
            section.payload for section in built["user-memory"].sections if section.title == "출력 프로필"
        )
        self.assertIn("basicProfile", str(profile))

    def test_stage_from_the_wrong_trace_is_skipped(self) -> None:
        memory_json = build_trace_json(_user_memory_trace())

        built = evidence.build(memory_json, "timeline")

        self.assertFalse(built.applicable)
        self.assertIn("generate-timeline", built.skip_reason)


class PromptSectionTests(unittest.TestCase):
    def test_json_array_is_not_mistaken_for_next_section_header(self) -> None:
        text = '[events]\n[{"clientEventId":"E1"}]\n\n위 목록으로 질문을 작성하세요.'
        body = evidence.prompt_section(text, "events")
        self.assertEqual(evidence.parse_json_array(body), [{"clientEventId": "E1"}])
        self.assertIn("위 목록", body)

    def test_multiple_json_arrays_are_not_silently_truncated(self) -> None:
        self.assertIsNone(evidence.parse_json_array('[{"clientEventId":"E1"}]\n[{"clientEventId":"E2"}]'))

    def test_missing_block_is_none_not_an_error(self) -> None:
        self.assertIsNone(evidence.prompt_section("[events]\n[]", "user memory"))
        self.assertIsNone(evidence.prompt_section(None, "events"))

    def test_block_body_stops_at_the_next_block(self) -> None:
        text = "[a]\n첫째\n\n[b]\n둘째"

        self.assertEqual(evidence.prompt_section(text, "a"), "첫째")
        self.assertEqual(evidence.prompt_section(text, "b"), "둘째")


if __name__ == "__main__":
    unittest.main()
