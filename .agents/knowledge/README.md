# Knowledge Index

이 폴더는 **여러 작업에서 반복 참조하는 지식**만 모읍니다. 계약·동작·불변식·관례·공통 언어가
여기 옵니다. 일회성 진행 기록·탐색 과정·결정 로그는 [.agents/worklog/](../worklog/README.md) 로,
구현 전 계획은 [.agents/plan/](../plan/README.md) 로 갑니다.

## 사용 방법

1. 구현 전, 아래 **Router** 에서 내가 건드릴 경로(`Related paths`)와 상황(`Read when`)에
   맞는 문서만 골라 읽습니다. 전체를 매번 읽지 않습니다.
2. 구현 후, 바꾼 경로를 `Related paths` 와 대조하고 `Update when` 에 해당하는 **의미 변화**가
   있었는지 확인합니다.
3. 파일이 바뀌었다는 이유만으로 문서를 고치지 않습니다. 계약·동작·불변식·운영 방식의
   의미가 달라진 문서만 같은 변경에서 갱신합니다.
4. 코드·설정·스키마·테스트·CI 가 이 문서들보다 **우선**합니다. 서로 다르면 코드를 정본으로
   보고, 의미가 바뀐 경우에만 문서를 맞춥니다.

## Router

| 문서 | Scope | Read when | Related paths | Update when |
| --- | --- | --- | --- | --- |
| [domain/overview.md](domain/overview.md) | 시스템 목적·데이터 원천·처리 파이프라인 | 전체 그림·범위를 잡을 때 | (전역) | 목적·데이터 원천·파이프라인 단계가 바뀔 때 |
| [domain/trace-json-spec.md](domain/trace-json-spec.md) | Task 리뷰 `trace.json` 저장 구조(정본·중복금지) | Page2 저장/표시, trace_builder 를 손댈 때 | `app/tasks/`·`app/ui/task_review.py`·`app/storage/` | trace.json 구조·정본·중복 규칙이 바뀔 때 |
| [domain/ubiquitous-language.md](domain/ubiquitous-language.md) | 프로젝트 공통 용어(도메인 이름·필드·개념) | 새 이름/필드/개념을 만들거나 바꿀 때 | (전역) | 용어의 정의·표기가 바뀌거나 새 핵심 용어가 확정됐을 때 |
| [conventions/issue.md](conventions/issue.md) | 이슈 제목·라벨 형식 | 이슈를 만들거나 제목을 고칠 때 | (해당 없음) | 허용 Type·아이콘·형식이 바뀔 때 |
| [conventions/commit.md](conventions/commit.md) | 커밋 분할·메시지 형식 | commit 을 나누거나 message 를 쓸 때 | (전역) | 커밋 분할 기준·message 형식이 바뀔 때 |
| [conventions/pull-request.md](conventions/pull-request.md) | PR 작성·검토 절차 | PR 을 만들거나 리뷰할 때 | `.github/` | PR 템플릿·검토 기준이 바뀔 때 |

## 새 문서를 추가하는 기준

- 여러 작업에서 반복해 읽을 가치가 있고, 기존 문서의 Scope 로 설명하기 어려울 때만 추가합니다.
- 추가하면 이 Router 표에 한 줄을 함께 넣습니다(Scope·Read when·Related paths·Update when).
- 실제 secret·credential·token·사용자 원문은 어떤 knowledge 문서에도 기록하지 않습니다.
