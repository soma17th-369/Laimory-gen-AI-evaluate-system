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

    def test_timeline_trace_covers_six_targets(self) -> None:
        self.assertEqual(
            list(self.evidences), ["event-photo", "event-notification", "timeline", "repair", "question", "final"]
        )

    def test_event_agent_only_sees_its_own_source(self) -> None:
        notification = self.evidences["event-notification"]
        payload = next(section.payload for section in notification.sections if section.title == "입력 source")

        self.assertEqual(set(payload), {"notifications"})
        prompt = evidence.build_user_prompt(notification)
        self.assertIn("noti-1", prompt)
        self.assertNotIn("stay-1", prompt)

    def test_empty_source_is_not_scored(self) -> None:
        trace_json = build_trace_json(_timeline_trace())
        trace_json["source"]["photos"] = []
        photo = evidence.build(trace_json, "event-photo")

        self.assertFalse(photo.applicable)
        self.assertIn("0건", photo.skip_reason)

    def test_final_compares_the_delivered_timeline_with_every_source(self) -> None:
        final = self.evidences["final"]
        sections = {section.title: section.payload for section in final.sections}

        self.assertEqual(set(sections["입력 수집 원본"]) >= {"stays", "movements", "notifications", "photos"}, True)
        self.assertEqual(sections["입력 User Memory"], "혼자 사는 개발자")
        self.assertIn("햄버거", str(sections["Vision 결과"]))
        # 질문은 질문 단계에서 따로 잰다.
        self.assertEqual(sections["출력 최종 타임라인"]["events"], [{"clientEventId": "event-001", "title": "고친 뒤"}])

    def test_summary_carries_the_pipeline_version(self) -> None:
        self.assertIsNone(self.evidences["timeline"].summary["pipelineVersion"])

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


_CLUE_DRAFT = {"events": [{"clientEventId": "event-001", "title": "점심을 먹음", "baseEventIds": ["E1"]}], "warnings": []}
_CONFIRMED = {"events": [{"clientEventId": "event-001", "title": "점심을 먹음", "description": "{place}에서 밥을 먹었다."}], "warnings": []}


def _v4_timeline_trace() -> SimpleNamespace:
    """v4 `generate-timeline` 한 건. 위치·일정은 코드가 만들고 사진·알림은 단서 호출이 낸다."""
    trace = _timeline_trace()
    kept = [
        obs
        for obs in trace.observations
        if not obs.name.startswith("event-agent-") and obs.name not in ("merge-event-results", "describe-photo-images")
    ]
    for obs in kept:
        if obs.name == "timeline-agent":
            obs.output = {"timeline": _CLUE_DRAFT}
        if obs.name == "generate-timeline-draft":
            obs.input = [
                {"role": "system", "content": "# Timeline 시스템 프롬프트\n\n## 당신의 역할"},
                {
                    "role": "user",
                    "content": "[draft metadata]\ndate: 2026-09-04\n\n[하루]\n집 → 회사\n\n[근거 묶음]\nB1 E1 회사 체류\n\n"
                    "[빈 시간]\n없음\n\n[알림]\n없음\n\n[user memory]\n혼자 사는 개발자",
                },
            ]
    clue_steps = [
        _obs(
            "clue-agent-photo",
            "AGENT",
            parent="main-agent",
            metadata={"agent": "photo", "sourceStage": "clue"},
            inp={"request": _REQUEST},
            out={"clueCount": 1, "warningCount": 0, "clues": [{"id": "P1", "rawId": "photo-1", "activity": "점심을 먹음"}]},
        ),
        _obs(
            "describe-photo-images",
            "GENERATION",
            parent="clue-agent-photo",
            inp=[{"role": "system", "content": "사진 묘사"}],
            out=[{"role": "assistant", "content": '{"descriptions":[{"rawId":"photo-1","description":"햄버거"}]}'}],
        ),
        _obs(
            "infer-photo-events",
            "GENERATION",
            parent="clue-agent-photo",
            inp=[{"role": "system", "content": "# 사진 해석 시스템 프롬프트"}],
            out=[{"role": "assistant", "content": "{}"}],
        ),
        _obs(
            "clue-agent-notification",
            "AGENT",
            parent="main-agent",
            metadata={"agent": "notification", "sourceStage": "clue"},
            inp={"request": _REQUEST},
            out={"clueCount": 1, "warningCount": 2, "clues": [{"id": "N1", "kind": "CONVERSATION", "rawIds": ["noti-1"]}]},
        ),
        _obs("build-clue-bundles", "CHAIN", parent="main-agent", metadata={"contract": "clue"}, out={"bundleCount": 1}),
        _obs(
            "confirm-timeline-draft",
            "CHAIN",
            parent="repair-agent",
            metadata={"phase": "initial"},
            out={"timeline": _CONFIRMED},
        ),
    ]
    trace.observations = kept[:1] + clue_steps + kept[1:]
    return trace


class PipelineVersionTests(unittest.TestCase):
    def _with_draft_system(self, text: str) -> dict:
        trace = _timeline_trace()
        for observation in trace.observations:
            if observation.name == "generate-timeline-draft":
                observation.input = [{"role": "system", "content": text}, observation.input[1]]
        return build_trace_json(trace)

    def test_clue_steps_mean_v4(self) -> None:
        self.assertEqual(evidence.pipeline_version(build_trace_json(_v4_timeline_trace())), "v4")

    def test_v1_to_v3_share_a_heading_and_differ_by_a_section(self) -> None:
        head = "# Timeline Agent 시스템 프롬프트\n\n## Laimory 공통 제품 비전\n\n"
        self.assertEqual(evidence.pipeline_version(self._with_draft_system(head + "## 1단계. 하루의 구조 파악")), "v3")
        self.assertEqual(evidence.pipeline_version(self._with_draft_system(head + "## 결과 문장의 말투")), "v2")
        self.assertEqual(evidence.pipeline_version(self._with_draft_system(head + "## 근거 우선순위와 융합 강령")), "v2")
        self.assertEqual(evidence.pipeline_version(self._with_draft_system(head + "## 핵심 판단 원칙")), "v1")
        self.assertIsNone(evidence.pipeline_version(self._with_draft_system(head)))

    def test_truncated_prompt_still_tells_the_version(self) -> None:
        trace = _timeline_trace()
        preview = '[{"content":"# Timeline Agent 시스템 프롬프트\\n\\n## 1단계. 하루의 구조 파악\\n…길다'
        for observation in trace.observations:
            if observation.name == "generate-timeline-draft":
                observation.input = {"body": {"truncated": True, "contentPreview": preview}}

        self.assertEqual(evidence.pipeline_version(build_trace_json(trace)), "v3")

    def test_user_memory_versions(self) -> None:
        def version(system: str) -> str | None:
            trace = _user_memory_trace()
            trace.observations[1].input = [{"role": "system", "content": system}, trace.observations[1].input[1]]
            return evidence.pipeline_version(build_trace_json(trace))

        self.assertEqual(version("`changes` 가 변경 목록이고\n### 장소 이름"), "v4")
        self.assertEqual(version("`changes` 가 변경 목록이고"), "v3")
        self.assertEqual(version("# User Memory 갱신 시스템 프롬프트"), "v2")


class V4EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trace_json = build_trace_json(_v4_timeline_trace())
        self.evidences = {item.key: item for item in evidence.build_all(self.trace_json)}

    def _section(self, key: str, title: str):
        return next(section.payload for section in self.evidences[key].sections if section.title == title)

    def test_v4_is_scored_on_the_same_targets(self) -> None:
        self.assertEqual(
            [key for key, item in self.evidences.items() if item.applicable],
            ["event-photo", "event-notification", "timeline", "repair", "question", "final"],
        )
        self.assertEqual(self.evidences["final"].summary["pipelineVersion"], "v4")

    def test_photo_and_notification_read_clues_not_result(self) -> None:
        photo = self._section("event-photo", "출력 단서")
        notification = self._section("event-notification", "출력 단서")

        self.assertEqual(photo["clues"][0]["activity"], "점심을 먹음")
        self.assertEqual(notification["clues"][0]["id"], "N1")
        self.assertEqual(self.evidences["event-notification"].summary["warnings"], 2)
        self.assertIn("햄버거", str(self._section("event-photo", "Vision 결과")))

    def test_photo_prompt_is_the_interpretation_call_not_vision(self) -> None:
        prompt = self._section("event-photo", "사진 해석 프롬프트")
        self.assertIn("사진 해석", str(prompt))

    def test_timeline_reads_the_clue_bundles_from_the_prompt(self) -> None:
        bundles = self._section("timeline", "입력 근거 묶음")

        self.assertEqual(bundles["근거 묶음"], "B1 E1 회사 체류")
        self.assertEqual(bundles["하루"], "집 → 회사")
        self.assertEqual(self._section("timeline", "입력 User Memory"), "혼자 사는 개발자")
        self.assertEqual(self._section("timeline", "출력 draft timeline"), _CLUE_DRAFT)

    def test_repair_starts_from_the_first_confirmed_draft(self) -> None:
        self.assertEqual(self._section("repair", "수정 전 draft"), _CONFIRMED)
        results = self._section("repair", "근거 원본")["eventResults"]
        self.assertEqual(results["photo"][0]["id"], "P1")

    def test_header_names_the_pipeline_version(self) -> None:
        self.assertEqual(self._section("timeline", "실행 정보")["pipelineVersion"], "v4")


class TruncatedPromptTests(unittest.TestCase):
    def test_recovers_complete_and_cut_messages(self) -> None:
        preview = '[{"content":"시스템 \\"지시\\"","role":"system"},{"content":"[user memory]\\n개발자\\n\\n[events]\\n[{\\"a\\": 1'
        messages = evidence.recover_messages(preview)

        self.assertEqual(messages[0], {"role": "system", "content": '시스템 "지시"'})
        self.assertEqual(messages[1]["role"], "user")
        self.assertTrue(messages[1]["truncated"])
        self.assertIn('[{"a": 1', messages[1]["content"])

    def test_cut_inside_an_escape_is_trimmed(self) -> None:
        messages = evidence.recover_messages('[{"content":"앞부분\\u12')
        self.assertEqual(messages[0]["content"], "앞부분")

    def test_truncated_user_prompt_marks_the_cut(self) -> None:
        trace = _timeline_trace()
        preview = '[{"content":"지시","role":"system"},{"content":"[user memory]\\n혼자 사는 개발자\\n\\n[AI Event'
        for observation in trace.observations:
            if observation.name == "generate-timeline-draft":
                observation.input = {"body": {"truncated": True, "contentPreview": preview}}
        timeline = evidence.build(build_trace_json(trace), "timeline")
        memory = next(section.payload for section in timeline.sections if section.title == "입력 User Memory")

        self.assertIn("혼자 사는 개발자", memory)
        prompt = next(section for section in timeline.sections if section.title.endswith("프롬프트"))
        self.assertIn("잘려", prompt.note)


class PromptSectionTests(unittest.TestCase):
    def test_korean_block_names(self) -> None:
        text = "[하루]\n집 → 회사\n\n[근거 묶음]\nB1\n\n[user memory]\n정보 없음"
        self.assertEqual(evidence.prompt_section(text, "근거 묶음"), "B1")
        self.assertEqual(evidence.prompt_section(text, "하루"), "집 → 회사")

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
