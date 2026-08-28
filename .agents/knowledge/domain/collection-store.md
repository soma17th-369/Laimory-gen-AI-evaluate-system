# 수집 저장소 (collection.json)

## Scope

LangFuse 트레이스를 로컬에 **누적 저장**하는 규칙과 증분 동기화 계약. 대시보드·Task 리뷰·
테스트 데이터 페이지가 공유하는 단일 원천이다. 여러 LangFuse 프로젝트(dev·prod)를 한 목록에
합쳐 담는다(→ [LangFuse 환경](langfuse-environments.md)).

## 정본 파일

| 파일 | 내용 | 불변식 |
| --- | --- | --- |
| `data/collection.json` | 지금까지 수집한 트레이스 요약 배열 | `id` 유일 · `timestamp` 내림차순(최신 먼저) · 한 번 들어온 행은 재수집으로 지워지지 않는다 |
| `data/collection.state.json` | **환경별** 동기화 커서 (`{"dev": {…}, "prod": {…}}`) | 각 값은 `backfilled` · `last_timestamp`(연속 훑기의 끝) · `last_synced_at` · `total`(그 환경의 저장 행 수) |

행 스키마(고정): `id` · `env` · `taskId` · `name` · `timestamp` · `user_id` · `latency` ·
`total_cost`. `taskId` 는 `trace.input` 에서만 나온다(LangFuse 서버측 필터 불가).
`env` 는 이 행이 어느 LangFuse 프로젝트에서 왔는지이며, 화면이 개발/운영을 구분하는 **유일한**
근거다. `env` 가 없는 행은 환경 구분이 생기기 전 데이터라 `dev` 로 읽는다.

## 동기화 계약

- **합쳐 담기**: 저장 파일은 하나다. 환경으로 폴더를 나누지 않고 행의 `env` 로 구분하며,
  정렬은 환경과 무관하게 `timestamp` 내림차순이다. 트레이스 id 가 전역 유일이라 `id` 병합이
  그대로 성립한다.
- **커서는 환경마다**: `sync(env)` 는 한 환경만 훑고 그 환경의 커서만 옮긴다. 다른 환경의 행도
  커서도 건드리지 않는다. 커서를 하나로 합치면 두 프로젝트가 서로를 밀어내 양쪽 다 구멍이 난다.
  환경 구분이 없던 시절의 평면 커서(`{"backfilled": …}`)는 `dev` 것으로 읽는다.
- **누적**: 수집은 교체가 아니라 `id` 기준 병합이다. 같은 `id` 는 새로 받은 값으로 갱신하고,
  LangFuse 가 더 이상 돌려주지 않는 행도 저장소에는 남는다.
- **커서**: `last_timestamp` 는 **연속으로 훑은 구간의 끝**이다. 이번 조회에서 실제로 받은 행의
  최신 시각으로만 전진하며, 저장된 행 전체의 최대 시각이 아니다(최신 구간만 담긴 옛 스냅샷이
  남아 있을 때 커서가 튀어 중간 구간을 건너뛰는 것을 막는다). 다음 동기화는 이 시각부터
  (`from_timestamp`, 경계 포함) 조회하고 중복은 `id` 병합이 흡수한다.
- **전체 수집(backfill)** 조건: 커서가 없거나 사용자가 명시적으로 요청했을 때. 이때만
  `from_timestamp` 없이 처음부터 훑는다.
- **필터 없음**: 수집 대상은 항상 프로젝트 전체 트레이스다. name·user_id 같은 조회 필터를 두면
  커서가 어떤 범위를 훑은 것인지 달라지므로 도입하지 않는다.
- **필드**: 목록 조회는 `fields="core,io,metrics"`. `io` 없이는 `taskId` 를, `metrics` 없이는
  `latency`·`total_cost` 를 얻을 수 없다(제외하면 -1 이 온다). 관측치·스코어는 받지 않는다.
- **정렬**: 조회는 항상 `timestamp.asc`. 오름차순이라야 조회 중 새 로그가 들어와도 페이지가
  밀리지 않고, 중간에 끊겨도 `last_timestamp` 가 안전한 워터마크가 되어 다음 실행이 이어받는다.

## Related paths

`app/collect/sync.py`(구현 정본) · `app/environments.py`(환경 키) · `app/storage/paths.py`(경로) ·
`app/ui/log_collection.py`(UI) ·
소비자: `app/ui/dashboard.py` · `app/ui/task_review.py` · `app/ui/testdata.py`

## Update when

저장 파일·행 스키마·커서 의미·누적/병합 규칙·조회 정렬·환경 표시 방식이 바뀔 때.
