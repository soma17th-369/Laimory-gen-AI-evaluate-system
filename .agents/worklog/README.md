# Worklog

작업 중/후의 **진행·결정·근거·막힌 점**을 날짜별로 남깁니다. 탐색 과정, 시도했다 접은 방법,
"왜 이렇게 했는지" 같은 raw note 는 전부 여기로 옵니다.

## Knowledge 와의 차이

- **Worklog** = 그때그때의 진행 기록(session memory, raw note). 시간순으로 쌓입니다.
- **Knowledge** = 여러 작업에서 반복 참조하는 계약·불변식·관례. 정제된 상태로 유지됩니다.

worklog 에 적은 내용이 "앞으로 계속 참조할 규칙" 으로 굳으면, 그때 정리해서
[knowledge](../knowledge/README.md) 로 승격합니다. worklog 자체는 knowledge 에 넣지 않습니다.

## 파일 규칙

- 파일명: `YYYY-MM-DD-<주제>.md` (하루에 여러 주제면 주제별로, 한 주제면 `YYYY-MM-DD.md`).
- 지우지 않고 append 로 쌓습니다.
- 실제 secret·token·사용자 원문은 적지 않습니다.

## 항목 골격

```markdown
# YYYY-MM-DD <주제>

## 한 일
무엇을 왜 했는지.

## 결정과 근거
어떤 선택을 왜 했는지. 접은 대안이 있으면 함께.

## 막힌 점 / 열린 질문

## 다음 할 일
```
