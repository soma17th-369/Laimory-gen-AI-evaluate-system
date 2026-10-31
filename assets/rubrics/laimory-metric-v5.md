<!--
status: awaiting-human-review
source_path: raw/notes/라이모리 정량적 메트릭 초안.md
note: 단계별 LLM-as-a-Judge 의 채점 기준 정본. 이 파일의 절이 그대로 채점 프롬프트가 된다.
      항목을 지우거나 요약하지 않는다. 배점을 고치면 app/analysis/stages.py 도 같은 커밋에서 고친다.
-->
## 문서 목적
이 문서는 Laimory의 각 Agent 결과를 LLM-as-a-Judge가 채점할 때 확인해야 할 측정 기준을 정리한다.
- `LLM 확인`: 원본 입력과 결과의 의미를 대조해야 하는 기준
- `코드 측정`: 형식, 개수, 비율, 길이, 시간을 정해진 식으로 계산하는 기준
- 각 평가 대상은 항목별 배점을 합산하여 100점 만점으로 채점한다.
- 코드 측정값이 제공되면 LLM은 숫자를 다시 추측하지 않고 그 값을 사용한다.
- 모범 Timeline이 있으면 참고할 수 있지만 필수는 아니다. 모범 예시가 없으면 입력 source와 Agent 결과를 직접 대조한다.
- 평가할 입력이 없는 기준은 감점하지 않고 같은 평가 대상 안의 다른 기준으로 배점을 비례 배분한다.
- Sleep / Activity Agent는 deprecated 상태이므로 채점 대상에서 제외한다.
LLM은 점수와 함께 감점 이유를 남긴다. 입력에서 확인되지 않는 사실이 1건 이상 생성된 경우, 아래에서 정의한 필수 반영 source가 1건 이상 누락된 경우, 민감정보 pattern이 1건 이상 검출된 경우에는 점수와 별개로 해당 입력과 출력 위치를 명시한다.
만약 정답이 있다면 적절한, 과도한 등 주관적인 표현은 그 정답을 기준으로 판단하면 된다.
### 판정 용어
아래 용어는 문서 전체에서 같은 조건으로 판정한다.
|용어|판정 조건|
|---|---|
|source 일치 주장|주장의 사람·장소·활동·시간이 참조된 rawId의 필드 또는 해당 Agent에 허용된 User Memory 필드에서 확인되고, 서로 충돌하는 입력이 없는 주장|
|source 불일치 주장|주장의 사람·장소·활동·시간 중 하나 이상이 참조된 입력에 없거나 입력값과 다른 주장|
|동일 사건|시간 구간이 겹치거나 간격이 10분 이하이면서, 같은 Calendar 일정 ID를 사용하거나 장소·활동·사람 중 두 항목 이상이 일치하는 두 candidate·fragment·event|
|중복 event|같은 rawId가 둘 이상의 event에 사용됐거나, 동일 사건 조건을 만족하는 둘 이상의 event|
|독립 source|rawId가 서로 다르고 sourceType도 서로 다른 source|
|필수 반영 source|평가 입력의 candidate, 오류 없이 읽힌 Calendar rawId, 오류 없이 분석된 Photo rawId, Location의 MOVEMENT 및 아래 체류 포함 조건을 만족한 STAY|
|반복 정보|같은 내용이 서로 다른 날짜의 입력에서 2회 이상 확인된 정보|
|최신 기록|평가 입력에서 timestamp가 가장 늦은 기록|
|유지 대상 정보|입력 source에서 확인되고 최신 기록과 충돌하지 않는 기존 profile 정보|
|직접 복사 문장|공백·문장부호·대소문자를 정규화한 뒤 candidate·fragment 문장과 문자열이 같은 문장|
|중복 질문|정규화한 문자열이 같거나 embedding cosine similarity가 0.90 이상인 질문 쌍|
|EventType 일치|event의 활동이 EventType 정의에 포함되면 해당 타입, 어떤 타입 정의에도 포함되지 않으면 `UNKNOWN`으로 분류된 상태|
|warning 필수 조건|source Agent 실패, 동일 field의 source 값 충돌, 사용한 rawId의 sourceRefs 누락, 민감정보 pattern 검출, parse·vision 실패 중 하나 이상이 발생한 상태|
## 1. Event Agent
Event Agent 하나를 평가할 때 공통 기준 20점과 해당 source Agent 기준 80점을 합산한다.
### 1.1 공통 기준 — 20점
|측정 기준|LLM 확인|코드 측정|배점|
|---|---|---|---|
|출력 형식|지정된 JSON 구조와 필드 의미를 지켰는가?|JSON parse, Pydantic schema 통과 여부|5|
|시간 형식|출력 시간이 입력과 일치하고 KST 의미를 유지하는가?|timezone offset 포함 ISO 8601 준수율|5|
|Window 준수|입력 window 밖의 사건을 만들지 않았는가?|window 밖 candidate·fragment 수|5|
|Source 일치|출력의 사람·장소·활동·시간이 참조한 입력 source에서 확인되는가?|입력에 없는 rawId 수, sourceType 불일치 수, source 불일치 주장 수|5|
### 1.2 Location Agent — 80점
#### 이동 흐름 — 20점
LLM 확인:
- 여러 MOVEMENT 사이에 20분 이하의 STAY만 있으면 하나의 이동 candidate로 묶었는가?
- 장거리 이동은 출발지와 최종 도착지를 중심으로 표현했는가?
- 마지막 MOVEMENT 종료 후 30분 안에 추가 MOVEMENT가 없으면 해당 이동 묶음을 종료했는가?
- MOVEMENT 사이의 STAY가 20분을 초과하거나 MOVEMENT 사이 간격이 30분을 초과하면 서로 다른 이동 candidate로 분리했는가?
코드 측정:
- MOVEMENT rawId 반영률
- 출발지·최종 도착지 보존율
- 하나의 MOVEMENT 묶음이 둘 이상의 candidate로 분리된 수
- 20분 STAY, 30분 이동 종료 정책 위반 수
#### 체류 병합과 제외 — 15점
LLM 확인:
- MOVEMENT 없이 이어지고 places 또는 address가 같은 STAY를 합쳤는가?
- 20분 이하 STAY의 시작 10분 전과 종료 10분 후에 MOVEMENT가 모두 있을때 독립  STAY candidate가 생기면 안된다.
- 20분 이하 STAY라도 앞 뒤 10분 안에 MOVEMENT가 없거나 정규화한 place·address가 같은 STAY가 2회 이상 나타나면 이들을 합쳐 candidate 로 만들었는가?
- 앞 MOVEMENT의 도착지와 뒤 MOVEMENT의 출발지가 같고 두 이동의 간격이 30분 이상인 경우 체류로 만들었는가? 
코드 측정:
- STAY rawId 반영률
- 동일 장소 연속 STAY 병합 수
- 10분·20분 경계 정책 위반 수
- 동일 rawId 중복 사용 수
#### 이동수단과 산책 추론 — 10점
LLM 확인
- 정규화한 출발지와 도착지가 비슷하고 코드의 속도 구간이 도보에 해당하면 산책이고 EXERCISE로 분류했는가? 
- 코드의 차량 속도 구간에 해당하는 이동을 EXERCISE로 분류하지 않았는가?
- 이동 거리·시간이 GPS 오차로 잘못 수집된 기준 이하인 기록을 candidate로 만들지 않았는가? 
코드 측정:
- 이동수단이 언급된 candidate 수
- 속도 구간과 이동수단 규칙 불일치 수
- 출발지·도착지 동일 candidate 수와 EXERCISE 변환 수
#### 장소·주소와 활동 추론 — 15점
LLM 확인:
- 출력 address가 입력 address와 문자열로 일치하고, places가 하나이면 그 값을 사용하며 둘 이상이면 임의로 하나를 선택하지 않았는가?
- 근거 없이 집·학교·회사로 단정하지 않았는가?
- 위치만으로 식사·대화·업무 같은 활동 목적을 확정하지 않았는가?
- 관측 마지막 시각 이후나 window 밖을 계속 추론하지 않았는가?
코드 측정:
- place·address source 일치율
- 입력에 없는 place·address 수
- 마지막 관측 이후 candidate 수
- 금지 place 표현과 URL·좌표 사용 수
#### 제목·설명·불확실성 — 10점
LLM 확인:
- 이동 문장에는 입력에서 확인되는 출발지와 도착지를 언급하고 출발지에서 도착지로 `갔다`, 체류 문장에는 체류했다 하지 않고 장소와 `시간을 보냈다`는 표현을, 산책 문장에는 장소와 `산책했다`는 표현을 포함했는가?
- 이동수단은 source 필드에 직접 기록됐거나 코드의 속도 구간 규칙과 일치할 때만 title·description에 포함했는가?
- title·description에 `GPS`, `센서`, `메타데이터`, `candidate`, `fragment`, `추론`, `관측 공백`, `데이터 공백`을 포함하지 않고, 해당 내용이 필요하면 uncertainty에 기록했는가?
코드 측정:
- title·description 누락 수
- source field가 충돌하거나 MOVEMENT 사이 공백에서 체류를 만든 candidate 중 uncertainty가 있는 비율
- 내부 분석 표현 사용 수
#### Source 전체 처리 — 10점
LLM 확인:
-  `window 밖`, `20분 이하이며 전후 10분 안에 MOVEMENT 존재`, `중복 rawId`, `parse 실패` 등이 아닌 모든 MOVEMENT와 STAY rawId가 candidate 또는 fragment에 포함됐는가?
코드 측정:
- Location source accounting rate
- candidate·fragment 어디에도 없는 rawId 수
- 중복 rawId 수
### 1.3 Calendar Agent — 80점
| 측정 기준            | LLM 확인                                                                                                         | 코드 측정                                   |  배점 |
| ---------------- | -------------------------------------------------------------------------------------------------------------- | --------------------------------------- | --: |
| 일정 반영            | 모든 Calendar rawId를 candidate·fragment에 포함했는가?                                                                  | Calendar rawId 반영률과 누락 수                |  20 |
| 제목과 시간           | Calendar title과 startAt·endAt을 candidate·fragment에 동일한 값으로 보존했는가?                                              | title·시간 exact match, 시간 오차             |  15 |
| EventType과 의미 태그 | event의 활동을 적절한 EventType 정의와 대조하고, title·description에 있는 활동·장소·사람을 의미 태그에 반영했는가?                               | EventType 일치율, eventType 분포와 UNKNOWN 비율 |  20 |
| 장소               | locationText를 places에 반영하고 URL을 장소로 사용하지 않았는가?                                                                 | locationText 보존율, URL place 사용 수        |  10 |
| 종일 일정            | all-day flag를 보존하고 window 의 startAt, endAt 과 동일한 startAt, endAt 을 설정했으며 description 에 `오늘은 하루종일` 이라는 내용을 넣었는가? | all-day flag 보존율과 정렬 위반 수               |  10 |
| 필수 필드            | 각 일정에 title·startAt·endAt·rawId를 포함하고, 입력에 참석자가 있으면 해당 참석자를 포함했는가?                                             | 필수 필드 누락 수                              |   5 |
### 1.4 Notification Agent — 80점
#### 알림 정보 유형 판단 — 15점
LLM 확인:
- 앱 이름만으로 판단하지 않고 대화, 결제·송금, 예약, 저우선순위 알림으로 내용을 구분했는가?
- 메신저 알림의 경우 앱과 송신자·내용의 맥락을 함께 보고 SOCIAL과 WORK 등을 구분했는가? ex) 카카오톡과 인스타그램은 SOCIAL, webex, discord, slack 등은 내용을 확인하고 WORK
코드 측정:
- 유형별 candidate·fragment 수
- UNKNOWN 비율
- 입력 알림 반영률
#### 메신저 — 20점
LLM 확인:
- 수신 알림을 사용자가 한 말로 착각하지 않았는가?
- 송신자 이름을 임의로 바꾸거나 관계를 만들어내지 않았는가?
- 수신만으로 답장이나 양방향 대화를 확정하지 않았는가?
- 해당 채팅방의 이름, 대상을 보고 몇 명이랑 대화했는지, 사적인 대화인지, 정보성 대화인지, 업무성 대화인지 구분을 잘 했는가?
- 메신저 기반 SOCIAL candidate를 하루 최대 3개로 제한했는가?
코드 측정:
- 메신저 기반 candidate 수
- SOCIAL 독립 event 수와 하루 최대 3개 정책 준수 여부
- 동일 대화 중복 candidate 수
#### 결제·송금 — 15점
LLM 확인
- 결제 알림에 음식점 상호가 있고 결제 시각이 식사 시간대 정책에 포함될 때만 MEAL로 분류했는가?
- 편의점·매장 결제를 SHOPPING으로 해석할 근거가 있는가?
- 결제와 메신저 알림의 메시지가 이어지는 경우에만 정산 맥락을 사용했는가?
- 결제 알림에 목적을 나타내는 상품·서비스·상호 정보가 없으면 식사·쇼핑·정산 목적을 title·description에 추가하지 않았는가?
코드 측정:
- 결제 알림 candidate·fragment 수
- 결제 알림 단독 목적 확정 수
- 동일 결제 중복 사용 수
#### 예약 — 15점
LLM 확인:
- 다른 날짜의 예약 알림을 오늘 방문·참석으로 착각하지 않았는가?
- 알림의 `예약 생성`, `예약 변경`, `예약 취소` 문구를 방문 완료로 표현하지 않았는가?
- 예약 알림의 업종·서비스가 EventType 정의와 일치하는 event에만 sourceRef로 추가하고, 예약 알림만 있으면 수행 완료를 표현하지 않았는가?
- 예약 알림에 명시된 시간이 오늘이면 cadidate 를 만들었으며 그 시간이 일치하는가?
코드 측정:
- 예약 날짜 오인 수
- 미래 예약의 오늘 event 승격 수
- 취소·변경 미반영 수
#### Noise와 개인정보 — 10점
LLM 확인:
- 다운로드·로그인·보안·일반 콘텐츠 알림만을 근거로 독립 candidate를 만들지 않았는가?
- 인증정보·전화번호·계좌번호 등 민감정보를 노출하지 않았는가?
코드 측정:
- 저우선순위 알림 독립 candidate 수
- 민감정보 pattern 검출 수
#### Source 보존 — 5점
LLM 확인:
- candidate·fragment에 적힌 송신자·결제·예약·대화 내용이 참조한 Notification의 sender·text·app·timestamp에서 확인되는가?
코드 측정:
- 사용된 Notification rawId 보존율
- candidate·fragment 어디에도 없는 rawId 수
### 1.5 Photo Agent — 80점
| 측정 기준          | LLM 확인                                                                                          | 코드 측정                               |  배점 |
| -------------- | ----------------------------------------------------------------------------------------------- | ----------------------------------- | --: |
| 사진 묘사          | vision 결과에 장소 유형·피사체·상황 단서·상호·시설명·행동·표정·소지품이 있으면 해당 항목을 빠짐없이 반영하고, vision 결과에 없는 항목은 추가하지 않았는가? | 묘사 필드 누락 수와 vision 결과 밖 claim 수     |  25 |
| Vision 결과 밖 주장 | 이미지에서 확인되지 않는 사람·장소·행동·감정·목적을 추가하지 않았는가?                                                        | vision 결과 또는 metadata에 없는 claim 수   |  15 |
| 사진 반영          | rawId와 촬영 시각을 읽었고 vision 처리되어 description이 존재하는 사진을 모두 candidate에 포함했는가?                        | Photo rawId accounting rate와 누락 수   |  20 |
| 사진 cluster 병합  | description 이 유사하고 촬영 시간 차이가 10분 이하인 사진을 같은 candidate로 묶었는가?                                    | 10분 이내 동일 cluster 수, 중복 candidate 수 |  15 |
| Source 보존      | 묶인 사진의 모든 rawId를 보존했는가?                                                                         | Photo rawId 누락·중복 수                 |   5 |
## 2. Timeline Agent — 100점
### 2.1 Event의 제목과 Description — 15점
LLM 확인:
- title과 descriptoin이 사용자가 자신의 하루를 기록한 것 같은 1인칭 주인공 시점, 해요체 과거형인가?
- title과 descriptoin이 단순히 언제 어디에 갔는 지 보고하는 게 아니라 참고할만한 다른 candidate 를 통해 무엇을 했는 지에 대해 적절히 연결했는가?
- title과 descriptoin이 관찰자·Agent 시점, 추정 표현과 내부 분석 과정을 노출하지 않았는가?
- title과 descriptoin 에 어디서, 무엇을 했는 지 내용이 들어가 있는가? 
- title과 descriptoin이 source에 시간·장소·활동 값이 있으면 description에 해당 시간대·장소·활동을 각각 포함했는가?
- 모르는 사실은 제외하고 uncertainty로 분리했는가?
- description이 직접 복사 문장에 해당하지 않는가?
- title이 30자 이하의 명사구이고 source의 활동명 또는 장소명 중 하나 이상을 포함하는가?
코드 측정:
- description 비어 있음 수
- 1~2문장 준수율
- description 120자 초과 수
- title 30자 초과 수
- 관찰자·추정·내부 분석 표현 사용 수
- 분 단위 시각·지속시간·걸음 수·거리·속도 노출 수
- 직접 복사 문장 수와 비율
### 2.2 하루 흐름과 필수 반영 사건 — 15점
LLM 확인:
- 단순한 사건의 나열이 아니라 전체적인 내용이 사람의 자연스러운 하루를 기록한 내용인가? (자연스러운 하루란? 집이던 숙소에서 하루를 시작하여 어딘가 이동해서 여러 활동들을 하거나 집에서 시간을 보내다가 다시 집이나 숙소로 들어오거나 계속 있었거나 해서 하루를 끝낸다.)
- timestamp가 가장 이른 사건, 모든 MOVEMENT 묶음과 도착지, 모든 Calendar·Photo 사건, timestamp가 가장 늦은 사건을 반영했는가?
- 필수 반영 해야할 캘린더, 사진들을 모두 event 또는 warning에 모두 연결했는가?
- 입력에 없는 사건을 새로 만들지 않았는가?
코드 측정:
- 최종 event 수
- source 근거가 없는 event 수
- source rawId accounting rate
- 동일 rawId·시간·장소의 중복 event 수
- 모범 예시가 있으면 필수 사건 반영률과 누락 수
### 2.3 Candidate와 Fragment 를 통한 이벤트 병합 — 25점
LLM 확인:
- 이벤트 병합이 이벤트 병합 조건을 만족했는가?
	- 서로 시간 범위가 겹쳐야 한다. (포함하거나 일부분 겹치는 경우 포함)
	- 위치는 전체 타임라인의 중요한 뼈대가 되며 이를 보충할 다른 근거가 없다면 독립적으로 Event 가 될 수 있다.
	- 위치의 places 에서 해당 Event 와 가장 적절한 장소명을 골랐는가?
	- 사진은 중요한 사건을 표현하며 누락되어서는 안되고 이는 위치 정보가 무조건 뒷받침되어야 한다.
	- 캘린더 일정 또한 중요 병합 기준으로 보며, 캘린더 일정과 시간대가 맞고 내용이 해당 일정의 근거가 되는 사진, 위치, 알림과 같이 병합되어야한다.
	- 알림은 메신저 알림의 경우 대화의 내용이 친목, 사적이라고 판단되면 다른 정보들과 독립적으로 SOCIAL 이벤트를 만들 수 있다.
	- 알림은 메신저 알림의 경우 대화의 내용이 캘린더 일정, 사진, 위치 등 다른 이벤트와 관련이 있다면 해당 이벤트의 내용을 보충하는 근거가 된다.
- 시간만 겹치고 장소·활동 내용·사람이 모두 다른 항목을 별도 event로 분리했는가?
- 특정 event 에 중간 이동, 새 일정, 다른 장소·사진·활동이 있어 서로 다른 event 인데 무리하게 이를 합치지 않고 event를 나눴는가?
- sourceRefs와 각 reason을 보존했는가?
- candidate 를 우선 근거로 활용하고 부족하거나 필요한 부분에 fragment를 이용하여 완성된 event 를 보충했는가?
- fragment의 사람·장소·활동·시간 중 하나 이상이 event의 같은 field와 일치할 때만 해당 event의 sourceRefs에 포함했는가?
- 시간만 겹치고 사람·장소·활동이 모두 다른 fragment를 event에 연결하지 않았는가?
- fragment만으로 독립 event를 만든 경우 동일 사건 조건을 만족하는 fragment가 2개 이상 존재하는가?
- 다운로드·보안·일반 콘텐츠 알림 fragment만으로 독립 event를 만들지 않았는가?
코드 측정:
- Candidate 변경·제외 수
- fragment 사용률
- fragment-only event 수
- 사용한 rawId의 sourceRefs 보존율
- 시간만 겹치고 사람·장소·활동이 모두 다른 sourceType 조합 수
- 동일 사건 조건을 만족하지 않는 항목의 병합 수
- 동일 사건 조건을 만족하지만 서로 다른 event로 출력된 수
- 동일 rawId의 여러 event 사용 수
- sourceRefs reason 작성률
- 3시간 초과 일반 event 수
- 모범 병합 label이 있으면 pairwise Precision·Recall·F1
### 2.6 Source별 최종 반영 — 12점
#### Location
- 하루의 주요 위치 이동을 설명하는 Location candidate 의 주요 cadidate 들을 전부 반영했으며 그 위치 이동이 이어지는 가?
코드 측정: MOVEMENT candidate 반영률, 출발지·도착지 보존율, source 또는 속도 구간 규칙에 없는 이동수단 사용 수.
#### Calendar
- 모든 calendar rawId 가 1개만 존재하는가?
- calendar 의 cadidiate 를 모두 반영했으며 해당 내용과 연관이 있는 것으로 보이는 위치, 사진, 알림 등의 정보와 모두 연결했는가?
코드 측정: Calendar 보존율, Calendar만 근거인 참석 완료형 event 수, 취소·변경 미반영 수, URL place 사용 수.
#### Photo
- 모든 photo candidate 가 최종 결과에 반영되었는가?
- 모든 photo rawId 가 정확히 1개만 존재하는가?
- Photo와 동일 사건 조건을 만족하는 event에 병합했는가?
- Photo와 동일 사건 조건을 만족하는 다른 candidate가 없을 때만 독립 PHOTO_MOMENT를 만들었는가?
코드 측정: Photo 단일 귀속률, 누락 수, 중복 귀속 수, 동일 사건 조건을 만족하는 다른 event가 있는 PHOTO_MOMENT 수.
#### Notification
- 예약·결제 알림 외에 해당 되는 일정으로 보이는 위치 정보, 사진, 캘린더 등의 candidate가 없으면 방문·행동 완료 event를 만들지 않았는가?
- 대화, 결제, 예약이 아닌 알림과 민감정보를 배제했는가?
코드 측정: 예약 날짜 오인, 미래 예약 오승격, 수신 알림만 있는데 답장·상호 대화를 추가한 수, 저우선순위 오사용, 민감정보 노출 수.
### 2.5 EventType — 8점
LLM 확인:
- 최종 event의 eventType이 EventType 정의와 대조해 일치하는 타입을 선택했는가?
- 선택한 eventType의 활동을 확인할 source field가 없으면 `UNKNOWN` 또는 해당 source의 기본 eventType을 사용했는가?
코드 측정:
- EventType별 event 수와 UNKNOWN 비율
- source 중심 타입 유지 수
- 모범 label이 있으면 Accuracy, 타입별 Precision·Recall·F1
| EventType        | 권장 단일 카드 상한        | 처리                              |
| ---------------- | ------------------ | ------------------------------- |
| `WAKE_UP`        | 0분                 | 시작·종료를 같게 고정                    |
| `PHOTO_MOMENT`   | 30분                | 여러 사진 장면이 길어지면 활동 타입으로 전환 또는 분리 |
| `MEAL`           | 60분                | 현재처럼 결정론적으로 제한                  |
| `MEETING`        | 4시간                | 초과 시 회의·후속 활동 분리                |
| `CLASS`          | 4시간                | 여러 강의·쉬는 시간 분리                  |
| `WORK`           | 4시간                | 오전·오후 작업처럼 분리                   |
| `EXERCISE`       | 4시간                | 장거리 활동은 강한 구간 근거가 있을 때 예외       |
| `SOCIAL`         | 6시간                | 식사·이동·모임 등 활동 변화가 있으면 분리        |
| `REST`           | 6시간                | 수면에 가까우면 `SLEEP`으로 분류           |
| `UNKNOWN`        | 3시간                | 근거가 약하므로 가장 보수적으로 제한            |
| `SLEEP`          | 원본 구간 또는 window    | 임의 절단 금지                        |
| `MOVEMENT`       | 원본 이동 구간 또는 window | 장거리 이동 보존                       |
| `CALENDAR_EVENT` | 원본 일정 구간 또는 window | 종일·다일 일정 보존                     |
### 2.7 시간 — 8점
LLM 확인:
- 모든 event의 startAt 과 endAt이 window 의  startTime·endTime 사이에 있는가? 벗어나지는 않았는가? 
- Calendar startAt·endAt이 window의 startTime·endTime과 
- MOVEMENT 시작·종료 시각을 출력에 같은 값으로 유지했는가?
- 여러 candidate를 병합하면 병합 대상의 가장 이른 startTime과 가장 늦은 endTime을 event 시간으로 사용했는가?
- 모든 Event 의 eventType 별 최소, 최대 시간이 지켜졌는가?
코드 측정:
- ISO 8601·timezone 준수율
- window 준수율
- 시간순 정렬 위반 수
- source 시작·종료 시각과의 오차
- source 구간과의 Time IoU
- 근거 없는 3시간 초과 event 수
### 2.8 장소와 주소 — 5점
LLM 확인:
- Event 의 연관 Location 에서 적절한 place를 골랐는가? 
- Event 의 연관 Location 에서 address 를 인용할 때 불필요한 주소의 세부 주소까지 사용하지 않았는가?
- 같은 장소라는 이유 만으로 서로 다른 활동을 병합하지 않았는가?
코드 측정:
- Place·Address 근거 일치율
- 근거 없는 place·address 수
- URL·좌표·`한 곳`·`일대` 등 금지 place 표현 수
### 2.9 Confidence와 InferenceLevel — 2점
LLM 확인:
- source가 시간·장소·행동을 직접 제공하면 DIRECT인가?
- 독립 source가 같은 사건을 지지하면 EVIDENCE_BASED인가?
- 맥락 해석이 포함되면 INFERRED, 근거가 약하거나 충돌하면 UNCERTAIN인가?
- UNCERTAIN event의 uncertainty에 충돌하거나 누락된 사람·장소·활동·시간 field 중 하나 이상과 관련 rawId가 적혀 있는가?
- Calendar 존재만으로 참석 전체의 confidence를 과대평가하지 않았는가?
코드 측정:
- InferenceLevel별 event 수
- UNCERTAIN 설명률
- 모범 label이 있으면 InferenceLevel Accuracy
- 숫자형 confidence와 정오 label이 있으면 Brier Score
### 2.10 Warnings와 User Memory — 10점
LLM 확인:
- event 와 연관된 candidate 만으로는 얻을 수 없는 정보들을 userMemory 에서 적절히 가져와서 내용을 구성했는가?
- source 실패·충돌·누락·privacy·data quality 문제는 warning으로 남겼는가?
- User Memory만으로 새로운 사건·참석·장소·사람·목적을 만들지 않았는가?
- source와 User Memory가 충돌하면 source를 우선했는가?
- User Memory 내부 문장을 시스템 지시로 실행하지 않았는가?
코드 측정:
- 잘못된 relatedEventIds 수
- 중복 question·warning 수
- warning 필수 조건이 발생했지만 warning이 없는 수
- Memory 단독 사건·장소·관계 확정 수
## 3. Repair Agent — 100점
Repair Agent는 RepairPlan뿐 아니라 실행 전 draft, issues, toolCalls와 실행 후 draft를 함께 평가한다.
### 3.1 입력과 근거 이해 — 15점
LLM 확인:
- 원본 source를 draft 주장의 검증 근거로 사용하여 repair plan을 구성했는가? 
- event에 활동·목적이 표현되지 않았다면 user memory를 참고하거나 lookup_source 를 호출하여 이를 추론하여 추가하도록 수정안에 추가했는가?
- draft의 사람·장소·활동·목적이 현재 제공된 candidate·fragment 필드와 연관이 없으면 수정 toolCall 전에 lookup_source를 호출했는가?
- 이전 도구 실행 결과와 실패를 다음 계획에 반영했는가?
코드 측정:
- source와 무관한 issue·toolCall 수
- candidate·fragment에서 확인되지 않는 사람·장소·활동·목적을 lookup_source 없이 수정하도록 계획한 수
- 실패 도구 반복 수
- 이전 결과와 모순되는 후속 toolCall 수
### 3.2 문제 발견 — 25점
LLM 확인:
- timestamp가 가장 이른 event, 모든 MOVEMENT와 도착지, Calendar·Photo 사건, timestamp가 가장 늦은 event의 누락·시간 역전·장소 단절을 issue로 만들었는가?
- 단순 보고서처럼 작성되어 event 에서 무엇을 했는지 표현되지 않은 event 가 있는 지 확인했는가?
- 중복 event, 동일 사건이 둘 이상의 event로 분리된 경우, 동일 사건 조건을 만족하지 않는 항목이 하나로 병합된 경우, 필수 반영 source 누락을 issue로 만들었는가?
- title·description의 1인칭 시점, 해요체, 일기체 처럼 표현되지 않은 문제를 찾았는가?
- 모든 event 들이 물리적으로 가능하도록 연결되었는지 확인했는가?
- 센서 상태나 분석 결과를 사건처럼 기록하거나 내부 용어와 원본 수치를 사용자 문장에 노출하지 않았는가?
- source 충돌, candidate·fragment 우선순위, Calendar·Photo 보존 문제를 찾았는가?
 - 시간: 이벤트 시간이 원본 근거와 일치하며 역전·겹침·범위 이탈·과도한 지속시간이 없는가?
- 장소: 이벤트의 장소와 주소가 원본 근거와 일치하는가?
- `rawId`: `sourceRefs`의 `rawId`와 `sourceType`이 실제 원본과 정확히 연결되는가?
- `confidence`: 이벤트의 `confidence`가 근거의 양과 신뢰도에 맞게 설정되었는가?
코드 측정:
- 알려진 문제 중 탐지한 수
- 문제 누락 수
- 테스트의 문제 label에 없고 source 불일치·누락·중복·형식 위반으로도 확인되지 않는 issue 수
- severity별 issue 수
### 3.3 Source 유형별 문제 수정 — 15점
LLM 확인:
- Fragment:
    - 다른 근거와 의미적으로 연결되지 않는 fragment만으로 독립 이벤트를 만든 문제를 찾았는가?
    - fragment 개수만으로 사건을 확정하지 않고, 사람·장소·활동·주제의 연결 여부를 검사했는가?
- Calendar:
    - Calendar 외 수행 근거가 없는데 참석·방문을 완료형으로 확정한 문제를 찾았는가?
    - 동일한 실제 사건을 가리키는 Calendar와 다른 이벤트가 중복된 문제를 찾았는가?
- Photo:
    - 최종 Timeline에서 누락되거나 여러 이벤트에 중복 귀속된 Photo를 찾았는가?
    - 사진의 내용·촬영 시각·장소와 일치하지 않는 이벤트에 귀속된 문제를 찾았는가?
    - Vision 결과에서 확인되지 않는 사람·행동·장소·방문 목적을 추가한 문제를 찾았는가?
    - 연결할 실제 사건이 있는데 별도의 `PHOTO_MOMENT`로 남긴 문제를 찾았는가?
- Location:
    - 주요 `MOVEMENT`, 이동의 도착지, 조건을 만족하는 `STAY`, 마지막 주요 이동의 누락을 찾았는가?
    - 하나의 연결된 이동을 여러 `MOVEMENT` 이벤트로 과도하게 나눈 문제를 찾았는가?
    - 이동 이후에도 이전 장소의 활동이 계속되는 것처럼 표현한 문제를 찾았는가?
    - 위치 정보만으로 활동 목적이나 집·학교·회사 같은 생활 장소를 확정한 문제를 찾았는가?
- Notification:
    - 미래 예약을 오늘 수행한 사건으로 만든 문제를 찾았는가?
    - 사용자 발신·답장 근거 없이 양방향 대화를 확정한 문제를 찾았는가?
    - 일반 공지·다운로드·로그인 알림처럼 약한 Notification을 독립 사건으로 만든 문제를 찾았는가?
코드 측정:
- Fragment·Calendar·Photo·Location·Notification별 정답 defect 수
- Source 유형별 탐지한 defect 수와 탐지율
- Source 유형별 누락한 defect 수
- Source 유형별 실제 defect와 연결되지 않는 issue 수
- Calendar 참석 오판, Photo 오귀속, Movement 누락 등 핵심 defect의 미탐지 수
### 3.4 Tool 선택과 실행 결과 — 20점
LLM 확인:
- 해당 되는 문제에 맞는 tool 을 선택했는가?
- 한 event의 한 field 문제에는 해당 event·field 수정 도구를 선택했는가?
- 한 event의 한 field 문제만 있는데 전체 Timeline 재실행 도구를 선택하지 않았는가?
- 둘 이상의 event 병합·분할 또는 시간순·장소 연결 문제에는 Timeline 재구성 도구를 선택했는가?
- parse 실패·rawId 누락·source field 변환 오류로 Event Agent를 재실행한 경우, 그 결과를 입력으로 Timeline도 재실행했는가?
- toolCall reason에 문제 근거와 기대 결과가 있는가?
-  수정 전 source와 일치하던 사람·장소·활동 값을 수정 후에도 같은 값으로 유지했는가?
코드 측정:
- 성공·실패 toolCall 수
- 결과를 바꾸지 않은 toolCall 수
- toolCall 이후 그대로 남은 issue 수
- issue와 연결되지 않은 toolCall·reason 수
| 구분    | 도구                                    | 역할                              | Draft 변경 |
| ----- | ------------------------------------- | ------------------------------- | -------- |
| 조회    | `lookup_source(rawId)`                | `rawId`에 해당하는 수집 원본 조회          | 아니요      |
| 편집    | `update_event(clientEventId, fields)` | 이벤트의 지정된 필드 수정                  | 예        |
| 편집    | `delete_event(clientEventId)`         | 근거가 없거나 잘못된 이벤트 삭제              | 예        |
| 시간    | `repair_durations()`                  | 0분 이벤트 복구 및 순간 이벤트 시간 보정        | 예        |
| 시간    | `align_location_events()`             | 체류·이동 이벤트를 원본 근거 시간에 맞춤         | 예        |
| 시간    | `enforce_meal_duration()`             | `MEAL` 시간을 20~60분으로 조정          | 예        |
| 시간    | `enforce_sleep_boundary()`            | 기상 이전 이벤트 제거 및 수면 경계 조정         | 예        |
| 장소    | `resolve_places()`                    | 근거 장소명 확정 및 근거 없는 주소 제거         | 예        |
| 캘린더   | `ensure_calendar_events()`            | Timeline에서 누락된 캘린더 일정 복원        | 예        |
| 병합    | `merge_stay_events()`                 | 이동 없이 이어진 같은 장소의 체류 이벤트 병합      | 예        |
| 중복    | `resolve_overlaps()`                  | 동일 사건 중복 병합 및 모순되는 겹침 경고        | 예        |
| 신뢰도   | `reinforce_calendar_location()`       | 캘린더와 체류 장소가 일치하면 신뢰도 보강         | 예        |
| 사진 검사 | `check_photo_assignment()`            | 사진의 누락·중복 귀속 검사                 | 아니요      |
| 재실행   | `rerun_event_agent(agent)`            | 특정 Event Agent의 후보·Fragment 재생성 | 간접 변경    |
| 재실행   | `rerun_timeline_agent()`              | 전체 후보로 Timeline을 다시 생성          | 전체 교체    |
### 3.5 관계없는 수정과 문제 수 변화 — 20점
LLM 확인:
- 문제가 있는 event와 field만 수정하고 정상 내용을 보존했는가?
- 원본이나 user memory에 없는 사람·장소 등을 새로 추가하지 않았는가?
- 하나의 문제를 고치면서 다른 사건을 훼손하지 않았는가?
- Repair 후 전체 문제 수가 Repair 전보다 감소했고 새로 생성된 source 불일치·누락·중복·형식 위반이 없는가?
코드 측정:
- 관계없는 event·field 수정 수
- 정상 event 삭제 수
- Repair 과정에서 새로 발생한 문제 수
- Repair 전후 전체 문제 수와 순감소량
### 3.6 완료 상태와 Summary — 5점
LLM 확인:
- 사용자 노출 문장인 `title`과 `description`에서 추정 표현(`~인 듯해요`, `아마`), 내부 용어(`GPS`, `센서`, `candidate`, `rawId`, `confidence`)와 원본 수치(`14시 37분`, `4,823걸음`, 위도·경도 등)를 제거하고 자연스러운 일기 문장으로 표현했는가?
- source 불일치·필수 source 누락·중복 event·형식 위반 또는 HIGH issue가 1건 이상 남아 있으면 `done=false`로 종료했는가?
- 미해결 문제를 해결됐다고 표현하지 않았는가?
- issue가 0건이면 toolCall도 0건인가?
- Summary에 issues의 ID·상태와 실행한 toolCall ID 및 미해결 issue ID가 누락 없이 들어 있는가?
코드 측정:
- 문제가 남은 `done=true` 수
- HIGH issue가 남은 종료 수
- issue가 없을 때 toolCall 수
- Summary와 issues·toolCalls 불일치 수
## 4. Question Agent — 100점
### 4.1 Event 이해와 근거 — 20점
LLM 확인:
- 질문이 전제하는 활동·장소·사람·시간대가 해당 event의 title·description·place·eventType에서 확인되는가?
- event에 이미 있는 사람·장소·활동·시간을 다시 묻지 않고, event에 없는 생각·감정·이유·인상 중 하나 이상을 묻는가?
- timeOfDay는 `아침`, `점심 무렵`, `오후`, `저녁`, `밤` 중 입력값에 대응하는 표현으로만 사용하고 시·분 숫자나 입력 timeOfDay 문자열을 그대로 쓰지 않았는가?
- event에서 비어 있는 사람·장소·행동을 질문에 추가하지 않았는가?
- User Memory의 선호 주제·호칭은 질문 표현에 사용할 수 있지만, User Memory에만 있는 사람·장소·활동을 해당 event의 사실로 쓰지 않았는가?
코드 측정:
- 입력에 없는 사람·장소·행동을 포함한 질문 수
- 정확한 시각을 만든 질문 수
- timeOfDay 입력 문자열을 그대로 사용한 질문 수
- User Memory에만 존재하는 사실을 전제한 질문 수
- User Memory가 `정보 없음`일 때 질문이 생성되지 않은 event 수
### 4.2 회고 유도 조건 — 30점
LLM 확인:
- 질문 대상이 해당 event에서 사용자가 경험한 행동·생각·감정·이유·인상·배운 점 중 하나 이상인가?
- 질문에 해당 event의 title·description·place·timeOfDay·활동 중에 관련 내용이 하나 이상이 포함됐는가?
- 예·아니오만 요구하는 단답형 질문이 아니라 행동·생각·감정·이유·인상·배운 점 등의 주관식 서술을 요구하는가?
- event에 이미 있는 발생 여부·장소·시각에 대해 다시 묻지 않았는가?
- 입력에 없는 감정·원인·평가를 질문의 전제로 단정하지 않았는가?
코드 측정:
- 예·아니오형 질문 수
- 서로 다른 event 2개 이상에 동일하게 사용된 정규화 질문 문구 수
- event title·place 표현 포함률
### 4.3 질문 표현 — 20점
LLM 확인:
- 질문이 `요?`로 끝나는 한 문장인가?
- 질문이 40자 이내로 끝나는가?
- 시스템 내부 수집·누락·추정·정확도·신뢰도를 노출하지 않았는가?
코드 측정:
- 물음표 종료율
- 문장 수
- 40자 초과 질문 수
- 내부 시스템 금지 표현 수
### 4.4 모든 Event의 질문 생성 — 20점
LLM 확인:
- 입력의 모든 clientEventId에 질문을 1개씩 생성했는가?
- 입력 event가 1개 이상인 모든 eventType에서 질문 미생성 event 수가 0인가?
코드 측정:
- 1차 질문 생성률
- 1차 누락 event 수
- 재요청 복구율
- 최종 질문 생성률
- eventType별 질문 생성률
### 4.5 질문 고유성과 연결 — 10점
LLM 확인:
- 서로 다른 event에 중복 질문을 생성하지 않았는가?
- event의 title·place·timeOfDay·활동 값이 다르면 질문에도 해당 값 중 하나 이상의 차이가 있는가?
- 질문이 전제하는 title·place·timeOfDay·활동이 연결된 clientEventId의 event와 일치하는가?
코드 측정:
- 완전히 동일한 질문 쌍 수
- 정규화 문자열이 같거나 embedding cosine similarity가 0.90 이상인 질문 쌍 수
- 입력에 없는 clientEventId 수
- 중복 clientEventId 질문 수
- Event 연결 정확률
## 5. User Memory Agent — 100점
### 5.1 입력 근거 구분 — 20점
LLM 확인:
- profile의 각 정보 단위에 title·subtitle·memo·event 중 출처 field를 기록하고, 해당 field 원문에서 그 정보를 확인할 수 있는가?
- title·subtitle에서 추출한 정보와 memo에서 추출한 정보의 provenance를 서로 다른 field 값으로 기록했는가?
- memo가 없고 title·subtitle에서도 같은 성향이 서로 다른 날짜에 2회 이상 확인되지 않으면 기존 personality·values·preferences·emotionalPatterns·memoryStyle 값을 바꾸지 않았는가?
- 완성된 timeline 의 event 들의 내용을 기반으로 routines·lifeContext·currentFocus 를 모두 추가했는가?
코드 측정:
- 근거 없는 성향 field 변경 수
- 성향 field 보존율
- 정보 단위별 provenance 누락 수
### 5.2 전체 갱신 방식 — 15점
LLM 확인:
- 기존 정보와 신규 정보가 같은 Field로 분류되면 이들을 모두 포함하도록 합쳤는가?
- 기존 정보가 최신 기록의 같은 field 값과 충돌하면 기존 정보를 제거하거나 최신 값으로 교체했는가?
- 이번 타임라인에서 추가되거나 병합되지 않은 기존 Field를 보존했는가?
코드 측정:
- 기존 정보와 신규 정보 중복 수
- 유지 대상 정보 삭제 수
- 최신 기록과 충돌하는 기존 정보 유지 수
### 5.3 근거 일치와 Field 배치 — 30점
각 문장을 독립적으로 검증 가능한 정보 단위로 나누어 확인한다.
### user memory 고정 필드 
| Field               | LLM 확인 기준                                                                                                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `basicProfile`      | 연령대·직업·역할·생애 단계가 title·subtitle·memo·event의 명시적 문장에 있다면 그들을 정확히 기록했는가? 명시하지 않았다면 title·subtitle·memo·event에서 추측하여 추가했는가?                                                   |
| `lifeContext`       | 삶의 상황·변화가 memo에 명시되었다면 이를 정확히 기록했는가? 명시하지 않았다면 기록된 title·subtitle·memo·event을 통해 추측하여 추가했는가?                                                                               |
| `relationships`     | 기록에서 등장하는 인물에 대한 관계 호칭 또는 관계 설명이 입력에 있다면? 이름만 있고 관계 표현이 없으면 관계를 추가하지 않았는가?                                                                                                 |
| `personality`       | title·subtitle·memo에서 사용자가 어떤 사람인지, 성격 및 성향을 가지고 있는지 추론하여 작성했는가? 기존에 저장된 정보와 합쳤거나 충돌되는 경우 최신의 것으로 대체했는가?                                                                   |
| `values`            | 가치 판단이 memo·title·subtitle에 명시되었다면 이를 반영했는가? 기존에 저장된 정보와 합쳤거나 충돌되는 경우 최신의 것으로 대체했는가?                                                                                       |
| `preferences`       | 좋아함·싫어함이 입력에 명시되었다면 이를 반영했는가? 기존에 저장된 정보와 합쳤거나 충돌되는 경우 최신의 것으로 대체했는가?                                                                                                      |
| `routines`          | `MEAL`, `MEETING`, `CLASS`, `WORK`, `EXERCISE`, `SOCIAL` 등의 eventtype인 event 가 있다면 시간대·eventType·활동을 모두 저장했으며, 기존에 동일한 값이 저장되어있으면 합치고 새로운 것이라면 추가했으며 충돌되는 것은 오래된 것을 삭제했는가? |
| `currentFocus`      | 목표·과제·고민이 최신 기록에 명시되었다면 이를 기록했는가? 기존 저장되어있으면 합치고 새로운 것이라면 추가했으며 충돌되는 것은 오래된 것을 삭제했는가?                                                                                      |
| `emotionalPatterns` | memo에 기록된 감정을 느끼는 부분, 선택한 감정들이 어떤 상황에서 어떤 감정을 느꼈는 지 기록했는가? 기존 저장되어있으면 합치고 새로운 것이라면 추가했으며 충돌되는 것은 오래된 것을 삭제했는가?                                                             |
| `memoryStyle`       | memo 가 작성된 문체, 문장 구성등을 분석해서 기록하고 기존 저장되어있으면 합치고 새로운 것이라면 추가했으며 충돌되는 것은 오래된 것을 삭제했는가?                                                                                       |
코드 측정:
- 근거 일치율
- field 배치 정확률
- 근거 없는 신규 정보 수
- 단일 날짜만으로 반복 성향을 확정한 수
- 최신 기록과 충돌하는 정보 수
### 5.4 Field 혼동과 customAttributes — 15점
LLM 확인:
- personality와 values, values와 preferences를 구분해서 추출했는가?
- routines와 currentFocus, lifeContext와 currentFocus를 구분해서 추출했는가?
- 자신이 아닌 주변 사람의 직업·역할을 사용자의 `basicProfile`에 넣지 않았는가?
- 고정 field 정의 중 어느 것에도 해당하지 않는 정보만 customAttributes에 추가했는가?
- 동일한 사람·장소·활동·시간·성향 주장을 둘 이상의 field 또는 customAttributes에 반복하지 않았는가?
코드 측정:
- field 간 중복 정보 수
- 고정 field와 겹치는 customAttributes 수
- 기존 속성과 병합 가능한 중복 속성 수
- customAttributes 개수와 값 길이
### 5.5 크기·압축·개인정보 — 20점
LLM 확인:
- 중복 정보와 최신 기록에 의해 부정된 정보를 제거하고, 유지 대상 정보는 남겼는가?
- 각 자연어 field가 500자 이하이고, 같은 정보 단위가 둘 이상의 문장에 반복되지 않았는가?
- 실명·이메일·상세 주소·전화번호·계좌번호·카드번호·인증정보와 날짜·분 단위 시각·걸음 수를 포함하지 않았는가?
- 인물 고유명사는 입력에 있는 관계 호칭으로, 장소 고유명사는 장소 유형으로 바꿨는가?
코드 측정:
- 각 자연어 field 200자 초과 수
- 전체 직렬화 글자 수
- 중복 정보 수
- 실명·이메일·상세 주소 포함 수
- 전화번호·계좌번호·카드번호·인증정보 포함 수
- 정확한 날짜·분 단위 시각·걸음 수 포함 수
- 일반화되지 않은 인물명 수
- 장소 유형으로 바뀌지 않은 장소 고유명사 수
## 6. 점수 작성 형식
LLM-as-a-Judge는 평가 대상 하나마다 다음 형식으로 결과를 작성한다.
```text
총점: 00/100
항목별 점수
- <항목>: 00/<배점>
감점 이유
- <문제와 입력·출력 근거>
코드 측정값
- <제공된 측정값 또는 계산 가능한 값>
```
항목별 점수의 합은 반드시 총점과 같아야 한다. 감점 이유에는 입력 rawId, 출력 event·candidate·question ID와 문제가 발생한 field 경로를 적는다.

그리고 종합 스코어를 기록한다.  종합 스코어는 100점 만점이고 각 파트 점수의 평균이다.
