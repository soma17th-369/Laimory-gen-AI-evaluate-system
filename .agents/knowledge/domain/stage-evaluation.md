# 단계별 채점 (계약)

Task 하나를 **평가 대상(Agent) 8개**로 나눠 각각 100점으로 채점한다. 채점 기준의 정본은
[assets/rubrics/laimory-metric-v5.md](../../../assets/rubrics/laimory-metric-v5.md) 이고, 코드는 그
문서를 자르고 배점을 고정할 뿐 기준 문장을 따로 들고 있지 않다.

## 평가 대상과 근거 위치

| stageKey | 대상 | 트레이스 | 입력 근거 | 출력 근거 |
| --- | --- | --- | --- | --- |
| `event-location` | Location Event Agent | `generate-timeline` | `source.stays` · `source.movements` | `event-agent-location.output.result` |
| `event-calendar` | Calendar Event Agent | `generate-timeline` | `source.calendars` | `event-agent-calendar.output.result` |
| `event-notification` | Notification Event Agent | `generate-timeline` | `source.notifications` | `event-agent-notification.output.result` |
| `event-photo` | Photo Event Agent | `generate-timeline` | `source.photos` + `describe-photo-images` 출력(vision) | `event-agent-photo.output.result` |
| `timeline` | Timeline Agent | `generate-timeline` | `merge-event-results.output.mergedResult` · `source.*` · 프롬프트의 `[user memory]` | `timeline-agent` 의 `timelineRef` |
| `repair` | Repair Agent | `generate-timeline` | 수정 전 draft · 근거 원본 · 회차별 `plan`·도구 실행 | `repair-agent` 의 `timelineRef` |
| `question` | Question Agent | `generate-timeline` | 프롬프트의 `[events]`(timeOfDay 포함)·`[user memory]` | `question-agent` 결과의 `events[].question` |
| `user-memory` | User Memory Agent | `update-user-memory` | `update-user-memory-profile` 프롬프트의 `[existing user memory]`·`[dailyTimelines]` | 같은 GENERATION 의 출력 프로필 |

Sleep/Activity Agent 는 문서에서 deprecated 라 대상이 아니다.

## 불변식

- **자기 입력만 본다.** 대상 서버는 Event Agent 5종에 수집 원본 전체를 똑같이 넘긴다. 근거를
  자를 때 그 단계가 담당하는 source 배열만 남긴다. 그래야 "자기 source 만 보고 만들었는지"를 잰다.
- **자르되 요약하지 않는다.** 남기기로 한 근거는 원문 그대로 넣는다.
- **기준은 항목에 묶어 전달한다.** 절을 통째로 붓지 않고 항목마다 `키 · 항목명 · 배점 · 확인 기준`
  한 덩어리로 만든다(→ `stages.criteria()`). 배점표를 따로 두지 않는다(배점이 항목 제목에 있다).
  항목의 기준이 비면 로딩이 실패한다.
- **채점 기준은 화면에서 고친다.** 설정 화면(`채점 기준 설정`)에서 항목·배점·확인 기준을 고쳐
  저장하면 `data/rubrics/<stageKey>.json` 이 생기고, 그때부터 **그 편집본이 채점 기준**이다
  (→ `stages.get()`). 프롬프트는 채점할 때마다 현재 항목으로 다시 만들어지므로 고친 내용이 바로
  다음 채점에 나간다. 저장 시 배점 합계 100점·항목 키 중복 없음·기준 비어 있지 않음을 검사한다.
- **화면과 프롬프트가 같은 것을 본다.** `StageEvidence.sections` 하나로 채점 프롬프트를 만들고
  화면도 그린다.
- **항목마다 점수와 이유.** 결과 모델을 배점표에서 만들기 때문에 항목이 빠지면 스키마 검증에서
  실패한다. `reason` 은 빈 값을 허용하지 않는다(만점이어도 확인한 내용을 적는다).
- **총점은 코드가 계산한다.** `applied=false` 항목의 배점은 나머지에 비례 배분하고
  `Σscore / Σ배점 × 100` 으로 정규화한다. 그래서 항목별 점수의 합과 총점이 항상 맞는다.
- **근거가 없으면 0점이 아니라 N/A.** 해당 source 가 0건이거나 단계가 실행되지 않았으면 채점하지
  않고 사유만 남긴다. 종합 평균에서도 빠진다.
- **종합 스코어 = 채점된 대상들의 단순 평균**(문서 규칙).
- **문서와 배점표는 함께 바뀐다.** `stages.validate()` 가 각 항목의 `marker` 구절이 문서 절에
  있는지 검사하므로, 문서에서 항목이 사라지거나 배점이 바뀌면 로딩이 실패한다.

## 채점 대상 트레이스 고르기

수집 목록의 대부분은 대상 서버의 **테스트 실행**이다(taskId 가 `task-test` 고정, 비용 0,
관측치 1~7개, session_id·tags 없음). 채점 대상은 이름이 `generate-timeline` 또는
`update-user-memory` 이고 taskId 가 UUID 형식인 트레이스다(→ `app/tasks/review.py` 의 `is_scorable`).

## 코드 측정 항목은 쓰지 않는다

문서에는 항목마다 `코드 측정` 이 붙어 있지만 **채점에 넣지 않는다.** 코드가 계산하지 않는 이상
채점자가 눈대중으로 센 숫자가 되고, 그 숫자는 검증할 수 없다. 파서는 `LLM 확인` 과 `코드 측정` 을
갈라 두되(섞이지 않게) 프롬프트·화면·결과 어디에도 코드 측정은 넣지 않는다. 나중에 결정론 코드로
계산하게 되면 그때 다시 넣는다.

## 저장

- 채점·저장 흐름의 정본은 `app/tasks/review.py` 의 `judge()` 다. 화면은 진행 표시만 덧붙이므로
  `streamlit` 없이도 같은 결과가 저장된다.
- **단계가 끝날 때마다 저장한다.** 프로세스가 도중에 끝나도 끝난 단계는 남는다. 근거인 `trace.json` 은
  채점 전에 먼저 저장하고, 함께 채점한 단계는 같은 `runId` 로 묶는다.
- **레코드 저장은 잠근다.** 화면과 다른 프로세스가 동시에 저장할 수 있으므로 `save_stages` 와 프롬프트
  레지스트리는 읽고-합쳐-쓰는 동안 `store.locked` 를 잡는다. 깨진 레코드는 빈 값으로 읽어 덮어쓰지 않고
  `CorruptJson` 으로 멈춘다.
- **상세는 저장본을 먼저 쓴다.** `load_trace_json()` 은 `schemaVersion` 과 `traceId` 가 맞는 `trace.json` 이
  있으면 LangFuse 를 부르지 않는다. 그래서 채점한 Task 는 보존 기간이 지나도 같은 근거로 다시 볼 수 있다.
- 채점 결과(최신): `data/evaluations/<taskId>.json` (`schemaVersion: 2`). 단계별로 갱신하고 종합은
  저장할 때마다 다시 계산한다. 근거 원문은 담지 않고 `trace.json` 으로 다시 만든다.
- 채점 **실행 이력**: `data/evaluations/history/<taskId>.jsonl`. 한 줄이 단계 1회 채점이고 덮어쓰지
  않는다. 같은 근거로도 실행마다 점수가 달라지므로(Repair 44.0 → 32.0 을 관측했다) 편차를 보려면
  이력이 필요하다. 한 번의 채점(`전체 채점` 등)은 `runId` 로 묶이고, 화면은 **Task → 채점 실행 →
  단계** 순서로 좁혀 본다.
- 줄마다 **대상 파이프라인이 쓴 비용**을 함께 남긴다: 그 단계의 `usage`(토큰·durationMs)와 Task
  전체의 `traceTokens`·`traceLatency`·`traceCost`. LangFuse 로그에서 온 값이고 **점수에는 반영하지
  않는다.** 채점 자체의 비용은 남기지 않는다.
- `schemaVersion` 이 없는 예전 레코드(7기준 0~10점 단일 카드)는 **읽기 전용**이다. 목록에서
  `구버전` 으로 표시하고, 비교할 때만 ×10 해서 100점 기준으로 환산한다.
- 채점 항목 편집본: `data/rubrics/<stageKey>.json`. 파일이 없으면 메트릭 문서 기본값을 쓴다.
- 채점에 실제로 쓴 기준 본문: `judge-stage-<stageKey>` 이름으로 프롬프트 레지스트리에 기록된다
  (어떤 기준으로 매긴 점수인지 되짚기 위한 기록이지, 기준의 정본은 아니다).
