# 개선책 레코드와 전후 비교

## Scope

개선책 파일의 **반영 상태 계약**과, 개선 history 가 반영 시기 전후를 비교하는 **규칙**.

## 레코드 (`data/improvements/<slug>.json`)

| 필드 | 뜻 |
| --- | --- |
| `slug`·`taskIds`·`instruction`·`plan` | 생성 당시 정보 |
| `createdAt` | 생성 시각(ISO). 없던 예전 파일은 파일 mtime 으로 채운다 |
| `status` | `draft`(미반영) / `applied`(반영됨) / `dropped`(보류) |
| `appliedAt` | 반영 시각(ISO). **`applied` 일 때만** 값을 갖는다 |
| `note` | 무엇을 반영했는지 메모 |

- 상태 필드가 없던 예전 파일도 그대로 읽는다(`draft` 로 정규화).
- 상태가 `applied` 가 아니면 `appliedAt` 은 비운다. 비교 대상 판정이 흐려지기 때문이다.
- 정본은 [app/improve/records.py](../../../app/improve/records.py). 화면은 이 모듈만 쓴다.

## 비교 규칙

- **시간축은 트레이스가 생긴 시각**(`collection.json` 행의 `timestamp`)이다. 평가 파일에는
  자체 시각이 없으므로 `taskId` 로 트레이스 행에 붙인다.
- **구간**: 반영 시각 오름차순으로 놓았을 때 개선책 하나가 맡는 구간은
  `[반영 시각, 다음 개선책 반영 시각)`. 마지막 개선책은 현재까지.
- **비교 대상**: 직전 개선책의 구간. 첫 개선책은 `반영 전 전체`.
- **점수는 task 당 한 번**만 센다. 하나의 taskId 에 트레이스가 여럿일 수 있다.
- 값과 **표본 수(n)를 항상 함께** 낸다. 점수는 채점한 task, 토큰·모델은 상세 조회한 트레이스만
  가지므로 표본이 작다. n 없이 평균만 보이면 오해를 만든다.
- 트레이스 `name` 별 분해를 함께 보여준다. 단계마다 비용 규모가 달라, 전체 평균만 보면
  구성비 변화가 개선 효과처럼 보인다.

## 모델·토큰의 출처

트레이스 목록 API 는 모델·토큰을 주지 않는다(`observations` 가 id 목록뿐). 필요할 때
GENERATION 관측치를 트레이스 단위로 조회해 `data/generations.json` 에 캐시한다
([app/collect/generations.py](../../../app/collect/generations.py)).

- 읽을 수 있는 모델명은 관측치의 **`model`** 필드다. `model_id`·`internal_model_id` 는 LangFuse
  내부 UUID 라 화면에 쓰지 않으며, `provided_model_name` 은 비어 있는 경우가 많다.
- 트레이스는 끝난 뒤 바뀌지 않으므로 캐시는 무효화하지 않는다.

## Related paths

`app/improve/records.py` · `app/improve/compare.py` · `app/collect/generations.py` ·
`app/ui/improvement.py` · `app/ui/improvement_history.py`

## Update when

레코드 필드·상태 값·구간 분할 규칙·표본 표기 원칙·모델명 출처가 바뀔 때.
