# LangFuse 환경 (dev · prod)

## Scope

LangFuse 프로젝트를 둘 이상 다루는 규칙. 어디까지 합쳐 보고 어디서 갈리는지, 키를 어떤 이름으로
읽는지를 정한다. 수집 저장 계약 자체는 [수집 저장소](collection-store.md) 가 맡는다.

## 환경 키

`dev`(개발) · `prod`(운영). 정본은 `app/environments.py` 의 `ENVIRONMENTS` 이고, 화면 라벨도
같은 모듈의 `LABELS` / `SHORT_LABELS` 만 쓴다. 화면이 문자열을 따로 만들지 않는다.

## 합쳐 본다

**두 프로젝트를 갈라 보지 않는다.** 수집한 로그는 한 목록에 시간순으로 함께 늘어놓고, 어느
프로젝트에서 왔는지는 행마다 붙는 `env` 값으로만 구분한다.

- 저장 경로를 환경으로 쪼개지 않는다(→ `app/storage/paths.py`). 트레이스 id 와 taskId 가 전역
  유일(32자리 hex · UUIDv7)이라 파일명이 부딪히지 않는다.
- 대시보드·로그 수집·Task 리뷰·채점 결과·개선책·개선 history·테스트 데이터 모두 한 목록을 보고,
  목록 위의 **환경 필터**(`전체` · `개발 (dev)` · `운영 (prod)`, → `app/ui/env_filter.py`)로 좁힐 수
  있다. 기본값은 `전체`다. 한 환경을 고르면 그 화면의 목록·건수·통계·전후 비교가 모두 그 환경
  것만으로 계산된다. 거르는 판단은 `environments.keep()` 하나로 한다.
- 필터 선택은 세션 동안 **페이지를 옮겨도 유지된다**(모든 화면이 같은 widget key 에
  `persist_state="session"`). 화면마다 따로 고르게 하지 않는다.
- 필터는 보기만 좁힌다. 수집(동기화)과 로그 수집 페이지의 환경별 수집 현황은 필터와 무관하게
  키가 설정된 환경을 모두 다룬다. 저장된 개선책(반영 상태)은 환경에 속하지 않아 거르지 않는다.
- 건수를 환경별로 나눠 보이는 것은 두 환경을 함께 볼 때만이다.
- 행 선택으로 상세를 여는 표는 필터 값을 widget key 에 넣는다. 선택은 행 위치로 돌아오므로
  필터가 바뀌면 옛 선택이 다른 행을 가리키지 않게 초기화한다.
- `env` 가 없는 데이터는 환경 구분이 생기기 전 것이라 `dev` 로 읽는다
  (`environments.of()`). 판단을 이 함수 하나에 모은다.

## 환경이 갈리는 자리 (셋뿐)

| 자리 | 왜 갈리나 | 어디서 |
| --- | --- | --- |
| 자격증명 | 프로젝트마다 키가 다르다 | `Settings.langfuse_credentials` |
| 조회 클라이언트 | 키가 다르니 클라이언트도 하나씩 | `langfuse_client.get_client(env)` |
| 동기화 커서 | "어디까지 훑었는지"가 프로젝트마다 다르다 | `collection.state.json` 의 환경별 map |

그 셋은 환경을 **명시적으로 받는다**(기본값 없음). 환경을 빠뜨렸을 때 조용히 한쪽만 조회하는
것보다 바로 드러나는 편이 낫다. 상세 조회(`get_trace`)·관측치 조회도 마찬가지로, **그 행의
`env`** 를 따라 보낸다.

## 자격증명

| 환경 | public / secret | host |
| --- | --- | --- |
| `dev` | `LANGFUSE_DEV_PUBLIC_KEY` / `LANGFUSE_DEV_SECRET_KEY` (없으면 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`) | `LANGFUSE_DEV_HOST` → `LANGFUSE_HOST` |
| `prod` | `LANGFUSE_PROD_PUBLIC_KEY` / `LANGFUSE_PROD_SECRET_KEY` | `LANGFUSE_PROD_HOST` → `LANGFUSE_HOST` |

- 접두사 없는 이름은 환경 구분이 없던 시절의 것이라 **dev 기본값으로만** 읽는다. prod 에는
  이 fallback 이 없다 — 운영 키를 넣지 않았는데 다른 프로젝트를 운영이라고 믿고 보는 일을 막는다.
- `host` 는 두 프로젝트가 같은 인스턴스에 있는 경우가 흔해서 공통 `LANGFUSE_HOST` 로 떨어진다.
- 어떤 이름이 어떤 환경으로 가는지는 `Settings.langfuse_credentials` **한 곳**에서만 정한다.
- 키 값은 `SecretStr` 로만 들고 다니고 SDK 생성자에만 넘긴다. 실제 값은 문서·로그·화면에 남기지
  않는다. 클라이언트 캐시도 환경 문자열을 key 로 쓴다(키를 캐시 key 로 쓰지 않는다).
- 수집은 `configured_environments()`(키가 갖춰진 환경)만 대상으로 한다. 키가 없는 환경은 화면이
  변수 이름을 알려주고 건너뛴다.

## Related paths

`app/environments.py`(환경 키·`of()`·`keep()`) · `app/ui/env_filter.py`(화면 공통 환경 필터) ·
`app/config.py`(자격증명) ·
`app/langfuse_client.py`(환경별 클라이언트) · `app/collect/sync.py`(환경별 커서·행의 `env`) ·
`app/collect/generations.py`(`(traceId, env)` 쌍으로 조회) · `app/ui/*`(환경 표시)

## Update when

환경 키가 늘거나 줄 때, 자격증명 변수 이름·fallback 규칙이 바뀔 때, 합쳐 보는 범위나 환경 표시
방식이 바뀔 때, 환경 필터가 적용되는 화면·범위나 유지 방식이 바뀔 때, 환경이 갈리는 자리가
셋에서 달라질 때.
