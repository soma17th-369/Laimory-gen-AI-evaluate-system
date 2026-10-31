## Calendar Event Agent 판정 예시

합성 입력 C1~C5: 오류 없는 일정 5개. C1~C4만 candidate 또는 fragment에 보존되면
schedule_coverage c01=4/5 → 16점. failedRefs=['C5']. 일정이 입력에 있는데 출력이
빈 배열이면 0/5 → 0점. Calendar 입력 자체가 없을 때만 이 조건은 N/A다.

입력 C1.locationText='https://example.invalid/meeting'. URL을 물리적 장소명으로 넣으면
place 기준 실패. 원문 URL을 장소로 사용하지 않고 장소를 비워 두는 것은 이 금지 조건 통과다.
단, 다른 명시적 실제 장소가 입력에 있으면 그 장소의 반영도 확인한다.

종일 일정이 0건이면 all_day c01=0/0. 종일 일정 C2가 있고 all-day flag를 삭제했다면
0/1이며 N/A가 아니다. 종일 표시와 원본 날짜가 보존되면 1/1 → 10점.
