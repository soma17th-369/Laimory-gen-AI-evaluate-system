# trace.json 저장 구조 (계약 · schemaVersion 2)

`data/tasks/<taskId>/trace.json` 은 한 Task 의 **전체 처리 과정을 중복 없이 재구성한 리뷰용
정규화 데이터**다. LangFuse Observation 을 복제한 로그가 아니라, `source→process→result`
흐름을 저장하고 Observation 간 중복은 참조로 연결한다. 구현: `app/tasks/trace_builder.py`.

v2 에서 바뀐 것: **단계별 채점에 필요한 근거를 버리지 않는다.** v1 은 step 의 `timeline` 키를
전부 지우고 `step.input`·`generation.output` 을 저장하지 않아, 저장된 파일만으로는 "어느 단계가
무엇을 받아 무엇을 만들었는지"를 알 수 없었다. LangFuse 보존기간이 30일이라 지나면 복구도 안 된다.

## 최상위 구조

```
trace.json
├── schemaVersion  # 2
├── task        # taskId·dailyRecordId·window·traceId·traceName·sessionId·tags·timestamp
├── source      # 수집 입력 정본 ← trace.input.request.*
├── process     # steps[] + generations[] + blobs{}
├── result      # 최종 timeline 정본 ← main-agent.output.timeline
├── operation   # 실행 상태·토큰·시간 ← trace.output (타임라인 제거)
└── langfuse    # observationCount 등 추적 메타
```

## 정본(canonical) — 중복 금지의 핵심

| 정보 | 정본 | 중복 처리 |
| --- | --- | --- |
| 최종 타임라인 | `result.timeline` | 다른 step 의 같은 timeline 은 저장 안 함 |
| 단계별 중간 타임라인 | `step.timelineRef` → `process.blobs` | 보존 대상 단계만 담고, 같은 내용이면 같은 ref 를 공유 |
| 수집 원본 | `source.*` | step.input 의 `request` 는 저장 안 함 → `inputRefs` 로 참조 |
| Agent 결과(candidate·fragment) | `event-agent-*.output.result` | repair 의 `eventResults` 는 저장 안 함 |
| 병합 결과 | `merge-event-results.output.mergedResult` | timeline-agent 의 `mergedResult` 는 저장 안 함 |
| 프롬프트·LLM 출력 | `generations[].inputRef`·`outputRef` → `blobs` | 같은 프롬프트가 여러 번 나와도 blob 하나 |
| Task 전체 토큰 | `operation.tokenUsage` | generations 합산으로 만들지 않음 |

`process.blobs` 는 `{ "b1": <값> }` 형태의 pool 이다. 내용 해시가 같으면 같은 키를 준다.
`trace_builder.resolve(trace_json, ref)` 로 꺼낸다.

## 단계 식별

`step.metadata` 에 대상 서버가 남긴 단계 식별자를 보존한다: `agent`(location·calendar·photo·
notification·sleep_activity·timeline·repair·question) · `sourceStage` · `iteration` ·
`maxIterations` · `tool` · `phase` · `stage` · `imageCount`. **이름 문자열 대신 이 값으로 단계를
찾는다** — 툴 실행 관측치는 이름에 괄호가 붙어 나온 사례가 있다(`execute-align_location_events()`).

실패는 `step.level`(DEFAULT·WARNING·ERROR)·`statusMessage` 로 남는다.

## timeline 을 보존하는 단계

`main-agent` · `timeline-agent` · `repair-agent` · `question-agent` · `confirm-timeline-draft` ·
`confirm-repair-iteration`. 나머지 step 의 `timeline` 키는 통과 중복이라 버린다.

## steps / generations

- `steps[]` = GENERATION 제외 관측치를 `start_time` 순 정렬, `order`·`parentId` 부여.
- `generations[]` = 각 GENERATION 한 번. `stepId` = `parent_observation_id`.
- `step.input`·`step.output` 은 다른 정본과 겹치는 키(`request`·`timeline`·`mergedResult`·
  `eventResults`·`system`·`prompt`·`snapshot`)를 뺀 나머지다.

## 구버전 파일

`schemaVersion` 이 없는 파일은 단계 근거가 없다. 채점 결과 화면은 그때 "재수집이 필요하다"고
안내하고, Task 리뷰에서 다시 열면 새 형식으로 저장된다.

> 요약: **trace.json 은 Observation 복제 로그가 아니라, source→process→result 를 한 번씩만
> 저장하고 반복되는 큰 값은 blob 참조로 접은 Task 단위 정규화 Trace.**
