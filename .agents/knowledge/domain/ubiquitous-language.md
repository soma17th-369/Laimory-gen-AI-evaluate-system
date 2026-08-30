# 공통 언어 (Ubiquitous Language)

프로젝트 전반에서 쓰는 **도메인 용어**를 한 곳에 모읍니다. 이름·필드·모델·개념을 만들거나
바꿀 때 여기를 따르고, 새 핵심 용어가 확정되면 여기에 추가합니다. 코드의 실제 식별자와
이 표가 다르면 코드를 정본으로 보고 표를 맞춥니다.

## 표기 규칙

- 표에는 **한글 용어 / 영문 표기 / 정의**를 함께 적습니다.
- 같은 개념을 여러 이름으로 부르지 않습니다. 대체 표기가 있으면 정의에 명시합니다.
- 코드 식별자(변수·필드명)는 코드가 생기면서 확정됩니다. 확정되면 정의에 병기합니다.

## 용어

| 한글 | 영문 표기 | 정의 |
| --- | --- | --- |
| LangFuse | LangFuse | 대상 API 서버가 생성형 AI 실행 과정을 남기는 관측 플랫폼. 이 도구의 입력 원천. |
| 트레이스 | Trace | LangFuse 에서 한 번의 실행 흐름 단위. |
| 생성 로그 | Generation | 트레이스 안의 LLM 호출 단위 로그(입력 프롬프트·출력·토큰 등). |
| 분석 | Analysis | 로그를 읽어 생성형 AI 의 동작 과정을 파악하는 단계. |
| 채점 기준 | Rubric | judge가 타임라인을 평가하는 규칙. 현재 `judge-rubric` v4는 7개 기준·overall과 v3 정량 Metric을 함께 사용한다. |
| LLM Provider | LLM Provider | 채점·프롬프트 개선·개선책·테스트 데이터 생성을 실행하는 공통 경계. 기본은 `CodexProvider`, deprecated 호환 구현은 `OpenAIApiProvider`다. 구조화 기능은 각 도메인의 Pydantic Schema를 쓴다. |
| 정량 Metric | Quantitative Metric | 점수 전에 입력 source와 최종 timeline을 대조해 계산하는 수치. 값·분자·분모·근거를 저장하며 계산 대상이 없으면 null이다. |
| 점수 | Score | grounding·temporal·place·coverage·composition·writing·question과 overall을 나타내는 0~10 정수. Metric을 핵심 근거로 삼되 단순 비율 환산은 하지 않는다. |
| 문제점 | Finding | 분석에서 식별한 품질 문제 하나. |
| 리포트 | Report | 분석·점수·문제점을 모은 산출물. 프롬프트 개선·테스트 데이터 생성의 근거. |
| 프롬프트 개선 | Prompt improvement | 리포트를 근거로 도출한 프롬프트 수정 방향. |
| 테스트 데이터 | Test data | 리포트를 바탕으로 생성한 검증용 입력·기대값. |

> 위 용어는 [시스템 개요](overview.md) 의 파이프라인과 짝을 이룹니다. 세부 필드·코드 표기,
> 세부 필드와 코드 식별자는 실제 스키마를 정본으로 봅니다.
