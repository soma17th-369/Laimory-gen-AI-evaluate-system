# trace.json 저장 구조 (계약)

`data/tasks/<taskId>/trace.json` 은 한 Task 의 **전체 처리 과정을 중복 없이 재구성한 리뷰용
정규화 데이터**다. LangFuse Observation 을 복제한 로그가 아니라, `source→process→result`
흐름을 **한 번씩만** 저장하고 Observation 간 중복은 참조로 연결한다. 구현: `app/tasks/trace_builder.py`.

## 최상위 구조 (6영역)

```
trace.json
├── task        # taskId·dailyRecordId·window (식별)
├── source      # 수집 입력 정본 ← trace.input.request.*
├── process     # steps[](실행 순서) + generations[](LLM 호출 정본)
├── result      # timeline 정본 ← main-agent.output.timeline
├── operation   # 실행 상태·토큰·시간 ← trace.output (타임라인과 분리)
└── langfuse    # observationCount 등 추적 메타
```

## 정본(canonical) — 중복 금지의 핵심

| 정보 | 정본 | 중복 처리 |
| --- | --- | --- |
| 최종 타임라인 | `result.timeline`(main-agent) | question-agent·store 등의 동일 timeline 은 저장 안 함. step output 에서 `timeline` 키 제거 |
| 수집 원본 | `source.*` | event-agent input 등에 반복돼도 저장 안 함 → step.`inputRefs` 로 `source.*` 참조 |
| 프롬프트 원문 | `process.generations[].input` | step 은 `generationRefs` 로만 가리킴 (§14 권고: prompts.json 분리 안 함, trace.json 통합) |
| 단계별 새 중간 산출물 | `process.steps[].output` | 해당 단계에서 **새로 생성/변경된 것만**. 단순 통과는 저장 안 함 |
| Generation 토큰 | `generations[].usage` | 호출 단위 |
| Task 전체 토큰 | `operation.tokenUsage` | trace.output 집계값. generations 합산으로 만들지 않음 |
| Event 근거 | `result.timeline.events[].sourceRefs`(rawId) → `source.*` | 별도 evidence 복제 금지 |

## steps / generations

- `steps[]` = GENERATION 제외 관측치를 `start_time` 순 정렬, `order`·`parentId` 부여
  (순차성+계층성 보존). GENERATION 은 `generations[]` 로 분리.
- `generations[]` = 각 GENERATION 한 번만. `stepId` = `parent_observation_id`(속한 step).

## 구현 상 휴리스틱 (실물 관측치 이름이 명세 예시와 정확히 일치하지 않아서)

- `inputRefs`: `store`/`finalize` → `result.timeline`; 하위 GENERATION 이름 키워드
  (location/notification/photo/calendar/health) → 해당 `source.*`. 그 외 `[]`.
- "의미 있는 step 선별"은 하지 않고 **GENERATION 제외 전 관측치**를 step 으로 둠(무손실).
  노이즈(반복 execute-* 등) 필터는 후속 보강 여지.
- `step.output`: `timeline` 키만 제거(최종 타임라인 중복 제거). 나머지 키는 보존.

> 요약: **trace.json 은 Observation 복제 로그가 아니라, source→process→result 를 한 번씩만
> 저장하고 중복은 참조로 잇는 Task 단위 정규화 Trace.**
