# .agents/skills 의 스킬 폴더를 .claude/skills 로 복사 동기화한다.
# .claude/skills 는 링크가 아니라 복사본이다. 스킬을 바꾸면 이 스크립트를 다시 실행한다.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root ".agents\skills"
$dst  = Join-Path $root ".claude\skills"

if (-not (Test-Path $src)) { throw ".agents/skills 가 없습니다: $src" }
New-Item -ItemType Directory -Force -Path $dst | Out-Null

# 기존 복사본(스킬 폴더)만 비운다. .gitkeep 등 파일은 남긴다.
Get-ChildItem -Directory -Force $dst | Remove-Item -Recurse -Force

# .agents/skills 의 스킬 폴더(하위 디렉터리)만 미러링한다. README.md 등 파일은 복사하지 않는다.
$skills = @(Get-ChildItem -Directory -Force $src)
foreach ($s in $skills) { Copy-Item -Path $s.FullName -Destination $dst -Recurse -Force }

Write-Host ("동기화 완료: {0} 개 스킬 (.agents/skills -> .claude/skills)" -f $skills.Count)
