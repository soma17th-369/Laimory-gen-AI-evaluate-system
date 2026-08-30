# 시스템 개요

## 목적

Laimory 의 생성형 AI가 남긴 실행 로그를 분석해 **품질을 측정·개선**하는 로컬 GUI 도구다.
대상 생성형 AI(대상 API 서버의 LLM 파이프라인)는 이 저장소 밖에 있고, 여기서는 그 서버가
**LangFuse** 에 남긴 관측 데이터를 소비한다.

## 데이터 원천

- **LangFuse** — 대상 API 서버가 생성형 AI 실행 과정을 남기는 관측 플랫폼.
  트레이스·generation(프롬프트·출력·토큰 등)을 읽어 온다.
- 이 저장소는 대상 서버의 코드·DB 에 직접 접근하지 않는다. **입력은 LangFuse 로그**다.

## 파이프라인

1. **수집** — LangFuse 에서 대상 실행 로그(트레이스/generation)를 가져온다.
2. **분석** — 생성형 AI 의 동작 과정을 파악한다(어떤 프롬프트로 무엇을 만들었는지).
3. **점수·문제점** — 품질을 수치화하고 문제점을 식별한다.
4. **리포트** — 분석·점수·문제점을 하나의 산출물로 모은다.
5. **활용** — 리포트를 바탕으로
   - **프롬프트 개선 방향**을 도출하고,
   - **테스트용 데이터**를 생성한다.

## 경계 (현재)

- **확정**: GUI 는 Streamlit(로컬 브라우저 실행), LangFuse 접근은 공식 Python SDK(`langfuse` v4).
  진입점은 `app/main.py`, 코드는 `app/` 패키지.
- **확정**: 채점·프롬프트 개선·개선책·테스트 데이터 생성의 공통 LLM provider는 ChatGPT 계정으로
  인증된 로컬 **Codex CLI**(`codex exec`)다. 각 호출은 ephemeral·read-only로 독립 실행하고,
  구조화 기능은 해당 Pydantic JSON Schema로 결과를 제한한다. OpenAI API 구현은 명시적으로만
  선택하는 deprecated 호환 provider이며 자동 fallback하지 않는다.
- **확정**: 하루 타임라인 채점은 `judge-rubric` v4를 사용한다. grounding·temporal·place·
  coverage·composition·writing·question의 7개 기준과 overall을 0~10으로 평가하며, 점수 전에
  AI 서버 v3가 정의한 20개 정량 Metric을 계산한다. v4는 v2 전체 기준과 v3 Metric 원본을
  합성한 버전이다.
- **미정**: 테스트 데이터 스키마의 최종 형태.
- 실제 secret·token(LangFuse 키·Codex 인증·OpenAI 키 등)·사용자 원문·프롬프트 원문은 문서·운영 로그·
  저장소에 남기지 않는다.
