# 2026-08-14 v4 정량 Metric 채점 호환

## 한 일

- AI 서버가 만든 v3 Metric 원본을 변경하지 않고 v2+v3을 합성하는 `judge-rubric` v4를 추가했다.
- 채점 결과에 composition 점수와 20개 Metric의 값·분자·분모·근거를 추가했다.
- judge 입력을 중복된 raw trace 대신 task/source 정본과 최종 timeline 전체로 구성하고 문자 수
  생략을 제거했다.
- Task 채점 화면, 저장 결과 화면, Markdown 리포트에 Metric 표를 연결했다.
- 합성 버전·스키마·빈 timeline·긴 source 근거를 검증하는 단위 테스트를 추가했다.

## 결정과 근거

- v3는 AI 서버 원본이므로 수정하지 않았다. v4가 v2와 v3을 `parts`로 참조하도록 해 원문과
  결합 관계를 명시했다.
- Metric 판정과 계산은 이번 범위에서 LLM structured output으로 유지했다. 대신 분자·분모를
  필수화해 결과를 감사할 수 있게 했다.
- 기존 `MED` 저장값은 읽을 때 `MEDIUM`으로 정규화해 v2 지침과 호환했다.

## 막힌 점 / 열린 질문

- 결정론으로 계산 가능한 산술을 코드로 옮기는 작업은 후속 범위다.
- 프로젝트에 pytest가 설치되어 있지 않아 동일 테스트를 표준 `unittest` runner로 실행했다.

## 다음 할 일

- 실제 OpenAI judge를 한 task에 실행해 20개 Metric 판정 품질과 토큰 사용량을 관찰한다.

## 채점 결과 화면 후속 조정

- Input/채점 결과 열을 1:1 비율, 작은 간격, 상단 정렬로 변경했다.
- score·finding·Metric 표를 내용 높이에 맞춰 줄바꿈되는 HTML 표로 바꿔 가로 스크롤을 제거했다.
- sidebar header 여백을 줄여 내비게이션 시작 위치를 위로 이동했다.
- 로컬 브라우저 1280×720 화면에서 두 열이 각 397px로 동일하고, 결과 표의
  `clientWidth == scrollWidth`이며 브라우저 console error가 없음을 확인했다.
