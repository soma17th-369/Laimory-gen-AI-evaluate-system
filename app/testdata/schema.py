"""테스트 케이스 계약 (M4b).

`input` 은 실제 수집 스냅샷의 **단순화 스키마**다(핵심 의미 필드만: 시각·장소·제목). rawId·좌표·
transports 같은 세부는 회귀/판정용 케이스엔 불필요해 생략한다. `expected` 는 자연어 기대 조건.
OpenAI structured output(strict) 이라 모든 필드가 required 이고 dict 자유형은 쓰지 않는다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TestStay(BaseModel):
    startAt: str = Field(description="ISO8601 시작")
    endAt: str = Field(description="ISO8601 종료")
    place: str | None = Field(description="장소명(없으면 null)")
    address: str | None = Field(description="주소(없으면 null)")


class TestMovement(BaseModel):
    startAt: str
    endAt: str
    fromPlace: str | None
    toPlace: str | None
    transport: str | None = Field(description="이동 수단(walk/car 등, 없으면 null)")


class TestCalendar(BaseModel):
    startAt: str
    endAt: str
    title: str
    locationText: str | None


class TestNotification(BaseModel):
    postedAt: str
    appName: str
    title: str
    text: str


class TestInput(BaseModel):
    date: str = Field(description="대상 날짜 YYYY-MM-DD")
    timezone: str = Field(description="예: Asia/Seoul")
    stays: list[TestStay]
    movements: list[TestMovement]
    calendars: list[TestCalendar]
    notifications: list[TestNotification]


class TestCase(BaseModel):
    title: str = Field(description="케이스 한 줄 제목")
    targets_criteria: list[str] = Field(
        description="검증 대상 기준 키(grounding/temporal/place/coverage/writing/question)"
    )
    description: str = Field(description="이 케이스가 무엇을 재현·검증하는지(한국어)")
    input: TestInput
    expected: list[str] = Field(description="기대 조건 목록. '이런 event 가 나와야/나오면 안 됨' 형태(한국어)")


class TestSuite(BaseModel):
    cases: list[TestCase]
    summary: str = Field(description="스위트 요약 1~2문장(한국어)")
