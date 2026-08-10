# Laimory-gen-AI-evaluate-system 에이전트 지침

이 저장소는 **Laimory 의 생성형 AI 품질을 측정·개선하기 위한 로컬 GUI 도구**입니다.
대상 API 서버(생성형 AI 파이프라인)가 **LangFuse** 에 남긴 실행 로그를 읽어 동작 과정을
분석하고, 점수를 매기고, 문제점을 파악합니다. 그 결과로 **프롬프트 개선 방향**을 도출하고,
리포트를 바탕으로 **테스트용 데이터**를 생성합니다.
로컬에서 `uv` 로 실행하는 Python **GUI 애플리케이션**을 목표로 합니다.
전체 그림은 [시스템 개요](.agents/knowledge/domain/overview.md) 를 참고합니다.
Codex 와 Claude 가 같은 프로젝트 지침을 공유하도록 이 파일을 공통 기준으로 사용합니다.

> 초기 저장소입니다. 애플리케이션 코드가 아직 거의 없고, 지금은 `.agents/` 스캐폴딩과
> 문서가 중심입니다. 구조·실행·배포가 정해지면 이 문서의 해당 섹션을 실제에 맞춰 갱신합니다.

## 기본 작업 방식

- 모든 md 파일은 한글을 base 로 작성합니다.
- 변경 전에는 관련 파일을 먼저 읽고 현재 구조를 기준으로 판단합니다.
- 불필요한 리팩터링이나 unrelated 변경은 하지 않습니다.
- 사용자가 명시하지 않은 파일 삭제, `git reset`, `checkout` 같은 파괴적 작업은 하지 않습니다.
- 기존 변경사항이 있으면 사용자 작업으로 보고 되돌리지 않습니다.
- 코드·설정·스키마·테스트·CI 가 문서보다 우선합니다. 서로 다르면 권위 원천(코드)을
  기준으로 판단하고, 의미가 바뀐 경우에만 문서를 맞춥니다.

## 작업 흐름 (Plan → 구현 → Worklog → Knowledge)

세 저장소는 목적이 다릅니다. 겹쳐 쓰지 않습니다.

- **Plan** — 규모 있는 작업은 구현 전에 [.agents/plan/](.agents/plan/README.md) 에 계획을
  먼저 남깁니다. 목표·범위·작업 분할·검증 방법을 적고, 커밋 단위로 쪼갭니다.
- **Worklog** — 구현 중/후의 진행·결정·근거·막힌 점은
  [.agents/worklog/](.agents/worklog/README.md) 에 기록합니다. raw note·session memory·
  탐색 과정은 전부 여기로 갑니다. Knowledge 에는 넣지 않습니다.
- **Knowledge** — 계약·동작·불변식·운영 방식처럼 **여러 작업에서 반복 참조할 지식**만
  [.agents/knowledge/](.agents/knowledge/README.md) 에 남깁니다.

## Knowledge Workflow

- 구현 전에 [Knowledge Index](.agents/knowledge/README.md) 의 Router 에서 변경 경로와
  `Read when` 이 맞는 문서만 골라 읽습니다. 전체 knowledge 를 매번 읽지 않습니다.
- 도메인 이름·필드·모델·용어를 만들거나 바꿀 때는
  [공통 언어](.agents/knowledge/domain/ubiquitous-language.md) 를 따릅니다.
- 코드 수정 후 변경 경로를 Router 의 `Related paths` 와 대조하고, 후보 문서의
  `Update when` 에 해당하는 의미 변화가 있는지 확인합니다.
- 파일이 바뀌었다는 이유만으로 문서를 갱신하지 않습니다. 계약·동작·불변식·운영 방식의
  의미가 달라진 knowledge 문서만 같은 변경에서 갱신합니다.
- 새 knowledge 문서는 여러 작업에서 반복해 읽을 가치가 있고 기존 문서의 Scope 로 설명하기
  어려울 때만 추가합니다. 작업 로그·session memory·raw note 는 넣지 않습니다(→ worklog).
- 실제 secret, credential, token, 사용자 원문은 knowledge 에 기록하지 않습니다.

## 이슈·커밋·PR

- commit·push·PR 은 사용자가 요청하거나 승인한 경우에만 수행합니다.
- 이슈를 만들거나 제목을 고칠 때는 [이슈 관례](.agents/knowledge/conventions/issue.md) 를
  따릅니다. `아이콘 Type - 한글 요약` 형식을 쓰고 아이콘을 생략하지 않습니다. 문서에 없는
  Type·아이콘은 임의로 만들지 않고 확인합니다.
- PR 을 작성·검토할 때는 [PR 관례](.agents/knowledge/conventions/pull-request.md) 를 따릅니다.
  저장소에 `.github/pull_request_template.md` 가 있으면 그 템플릿이 우선입니다.
- PR 을 준비할 때는 [커밋 관례](.agents/knowledge/conventions/commit.md) 에 따라 변경을
  독립적으로 검토·되돌릴 수 있는 작은 작업 단위로 나눕니다.
- commit 하나에는 하나의 주된 목적만 두고 unrelated refactor·formatting 을 섞지 않습니다.
  다만 code 와 필수 test 를 억지로 분리해 중간 commit 을 실패 상태로 만들지는 않습니다.
- commit message 는 `type : 한글 설명` 형식을 따르고, 무엇의 어떤 계약이나 동작을 바꿨는지
  구체적으로 적습니다.

## Python 환경

- Python 버전은 `.python-version` 과 `pyproject.toml` 기준을 따릅니다(생성되면).
- 이 프로젝트는 `uv` 와 `.venv` 를 사용합니다.
- 의존성 설치는 프로젝트 루트에서 `uv sync` 를 사용합니다.
- pytest 는 가능하면 `-p no:cacheprovider` 로 실행합니다. 검증이 끝나면 그 작업에서 만든
  임시 캐시(`.pytest-*`, `.test-tmp-*`, `pytest-cache-files-*`)를 저장소에 남기지 않고 삭제합니다.
- Windows 에서 기본 uv 캐시 권한 문제가 있으면 로컬 캐시를 사용합니다.

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv sync
```

## 실행

로컬에서 `uv` 로 띄우는 **Streamlit** 앱입니다(로컬 브라우저에서 열림). 진입점 파일은
부트스트랩 때 확정합니다(계획: `app/main.py`). 아래 명령은 부트스트랩 후 동작합니다.

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv run streamlit run app/main.py
```

- LangFuse 접근은 공식 Python SDK(`langfuse`)를 사용합니다. 키(public/secret)와 host 는
  환경변수(`.env`)로 주입하고, **키·로그 본문·프롬프트 원문은 저장소·운영 로그에 남기지
  않습니다.**

## 스킬 공유

- Codex 용 프로젝트 스킬 원본은 `.agents/skills/` 아래에 둡니다.
- Claude 쪽에서 공유할 때는 `.agents/skills/` 내용을 `.claude/skills/` 로 복사해 동기화합니다.
- `.claude/skills/` 는 링크가 아니라 복사본이며, 스킬을 바꾸면
  `scripts/link-skills.ps1`(Windows) 또는 `scripts/link-skills.sh`(bash)를 다시 실행해 갱신합니다.
- 자세한 규칙은 [.agents/skills/README.md](.agents/skills/README.md) 를 참고합니다.

## Project Structure

애플리케이션 코드는 아직 없습니다. 현재 저장소의 뼈대는 다음과 같고, 코드가 생기면 이
트리를 실제 구조로 확장합니다.

```
AGENT.md                       # 이 파일. Codex·Claude 공통 지침
.agents/                       # 에이전트 작업 자산(원본)
├── knowledge/                 # 반복 참조하는 지식(계약·관례·용어)
│   ├── README.md              #   Knowledge Index(Router): 어떤 문서를 언제 읽고 언제 고칠지
│   ├── domain/
│   │   └── ubiquitous-language.md   # 공통 언어(용어 사전)
│   └── conventions/
│       ├── issue.md           #   이슈 제목·라벨 관례
│       ├── commit.md          #   커밋 분할·메시지 관례
│       └── pull-request.md    #   PR 작성·검토 관례
├── skills/                    # Codex 용 프로젝트 스킬 원본(→ .claude/skills 로 동기화)
│   └── README.md
├── plan/                      # 구현 전 계획 문서
│   └── README.md
└── worklog/                   # 작업 진행·결정 로그(raw note)
    └── README.md
.claude/skills/                # .agents/skills 의 복사본(스크립트로 동기화)
scripts/
├── link-skills.ps1            # .agents/skills → .claude/skills 동기화 (Windows)
└── link-skills.sh             # .agents/skills → .claude/skills 동기화 (bash)
```
