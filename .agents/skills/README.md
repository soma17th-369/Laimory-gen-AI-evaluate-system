# Skills

이 폴더는 **Codex 용 프로젝트 스킬의 원본(source of truth)** 입니다. Claude 쪽에서 쓰려면
여기 내용을 `.claude/skills/` 로 복사해 동기화합니다.

## 구조

- 스킬 하나 = 하위 폴더 하나. 폴더 안에 `SKILL.md` 를 두고, 필요한 스크립트·자료를 함께 둡니다.

```
.agents/skills/
└── <skill-name>/
    ├── SKILL.md            # 스킬 정의(설명·사용법)
    └── ...                 # 보조 스크립트·자료(선택)
```

## Claude 로 동기화

`.claude/skills/` 는 링크가 아니라 **복사본**입니다. 스킬을 추가·수정·삭제한 뒤 아래 스크립트를
다시 실행해 갱신합니다. 스크립트는 `.agents/skills/` 의 **스킬 폴더만** `.claude/skills/` 로
미러링하며, 이 README 는 복사하지 않습니다.

```powershell
# Windows (PowerShell)
scripts/link-skills.ps1
```

```bash
# bash
bash scripts/link-skills.sh
```

## 규칙

- 원본은 항상 `.agents/skills/` 입니다. `.claude/skills/` 를 직접 고치지 말고 여기서 고친 뒤
  동기화합니다(직접 고치면 다음 동기화 때 덮어써집니다).
- 실제 secret·token·자격증명은 스킬에 넣지 않습니다.

> 아직 등록된 스킬이 없습니다. 첫 스킬을 만들면 위 구조로 폴더를 추가하고 동기화 스크립트를 실행합니다.
