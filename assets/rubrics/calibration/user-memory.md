## User Memory 판정 예시

합성 기존 preferences='차를 좋아함'. 최신 memo='이제 차보다 커피를 좋아한다'.
preferences 를 커피 선호로 고치고 관계없는 기존 문장을 남겼다면 merge_preserve c01·c03 통과.
관련 없는 기존 문장을 근거 없이 지웠다면 c01 실패다.

입력에 '동생은 간호사다' 만 있는데 사용자의 basicProfile 에 '간호사' 를 넣으면 placement c03 실패.

memo 없이 하루 기록 한 번에서 본 일을 '매주 운동함' 같은 습관으로 적으면 grounding c02 실패.
'한 번 운동함' 이나 '운동을 즐기는 것으로 보임' 으로 적으면 통과다.

그날의 회의·점심·이동을 routines 에 하나씩 옮겨 적으면 about_person c01 실패다.

항목 500자는 format_privacy c01 통과, 501자는 실패다. 전화번호 등이 없는 출력은 c02 통과이며 N/A 가 아니다.
v4 의 `places` 목록은 채점하지 않으므로 그 안의 장소 이름을 근거로 감점하지 않는다.
