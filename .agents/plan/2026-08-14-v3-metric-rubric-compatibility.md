# v4 정량 Metric 채점 호환

- 상태: 완료
- 관련 이슈:

## 배경·목표

AI 서버가 만든 `judge-rubric` v3에는 정량 Metric 정의만 있어 단독 system prompt로 사용할 수
없고, 채점 결과 스키마에도 composition과 Metric 출력 계약이 없다. v3 원본을 변경하지 않고,
v2의 완전한 평가 지침과 v3의 20개 Metric을 결합한 v4를 만들며 실제 judge 입력·출력·UI·리포트가
같은 계약을 사용하게 한다.

## 범위 / 범위 밖

- 포함: 완전한 기본 rubric, canonical 채점 근거, 7개 기준과 20개 Metric 스키마, UI/리포트 표시,
  단위 테스트, 관련 계약 문서.
- 범위 밖: Metric 판정을 전부 결정론 코드로 이전하거나 과거 평가를 자동 재채점하는 작업.

## 접근

v3 Metric을 변경 없이 완전한 v4 system prompt의 정량 평가 절로 포함한다. judge 입력은 중복된 trace 전체 대신
task/source 정본과 최종 timeline을 생략 없이 전달한다. 각 Metric은 값뿐 아니라 분자·분모와
계산 근거를 구조화해 저장한다.

## 작업 분할

- [x] 채점 rubric·입력 근거·결과 스키마 계약 정렬
- [x] UI와 리포트에 composition·Metric 표시 연결
- [x] 단위 테스트와 계약 문서 갱신

## 검증

- `uv run python -m unittest discover -s tests -v` (프로젝트에 pytest 실행 파일이 없어 표준 runner 사용)
- Python compile/import 확인
- 샘플 trace에서 canonical source와 최종 timeline이 채점 입력에 모두 포함되는지 확인

## 리스크·미결

- Metric의 의미 판정은 여전히 LLM judge가 수행하므로 완전한 결정론은 아니다.
- 매우 큰 trace는 모델 context 한도에 걸릴 수 있으며, 근거를 조용히 자르지 않고 명시적으로
  실패시키는 후속 정책을 검토할 수 있다.
