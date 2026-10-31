## Repair Agent 판정 예시

합성 수정 전 E1: place만 source와 다르고 title·시간·활동은 일치한다.
update_event로 E1.place만 근거 값으로 수정했다면 tool_selection의 단일 field 도구 선택
기준 통과. 같은 단일 문제만 있는데 전체 Timeline을 재실행했다면 해당 기준 실패.
여러 사건의 병합·분할 문제가 함께 있으면 전체 재구성 도구가 필요한지 그 근거로 재판정한다.

E1을 고치며 정상 E2를 삭제하면 unrelated_edits의 정상 내용 보존 기준 실패다.
E1 수정이 성공했다는 이유로 E2 훼손을 상쇄하지 않는다. 같은 E2 삭제를 동일 기준에서
두 번 세지 않는다. 서로 다른 명시적 기준 위반이면 그 기준에도 각각 반영한다.

source 불일치 문제가 남았는데 done=true면 done_summary의 미해결 문제 종료 기준 실패.
문제가 0건이고 toolCall도 0건이면 불필요 도구 호출 금지 기준은 통과이며 N/A가 아니다.
이 기준은 해당 Repair 회차 하나를 단위로 판정한다.
