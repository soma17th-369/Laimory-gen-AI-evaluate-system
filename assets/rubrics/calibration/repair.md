## Repair 판정 예시

합성 수정 전 E1: 자동 검사가 `DURATION_OVER_LIMIT` 을 짚었고, 그 안에 식사 사진 P1 이 있다.
Repair 가 P1 을 근거로 식사 event 를 나눴다면 grounded_fixes c04 통과. 근거 없이 길이만 보고 같은
문장의 조각 다섯 개로 나눴다면 c04 실패다. 길이 초과는 다시 보라는 신호이지 나누라는 지시가 아니다.

Repair 가 사진 귀속·시간 정렬처럼 코드가 확정한 값을 다시 검증하지 않은 것은 감점 사유가 아니다.
코드가 고쳐 틀 문장만 남은 E2 를 다시 쓰지 않고 끝냈다면 issue_resolution c03 실패다.

E1 을 고치며 문제가 없던 E3 를 지우면 unrelated_edits c01 실패다. E1 수정이 성공했다고 E3 훼손을
상쇄하지 않는다. 같은 E3 삭제를 같은 기준에서 두 번 세지 않는다.

해소할 findings 가 남았는데 done=true 로 끝냈다면 done_summary c01 실패. 문제가 0건이고 toolCall 도
0건인 회차는 done_summary c03 통과이며 N/A 가 아니다. 이 기준은 회차 하나를 단위로 한다.

v3 의 `absorb_location_event` 나 v4 의 `add_conversation_event` 처럼 한 버전에만 있는 도구를 썼다는
이유로 tool_use 를 실패시키지 않는다. 그 호출이 값을 바꿨는지, 근거와 맞는지만 본다.
