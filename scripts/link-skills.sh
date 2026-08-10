#!/usr/bin/env bash
# .agents/skills 의 스킬 폴더를 .claude/skills 로 복사 동기화한다.
# .claude/skills 는 링크가 아니라 복사본이다. 스킬을 바꾸면 이 스크립트를 다시 실행한다.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/.agents/skills"
dst="$root/.claude/skills"

[ -d "$src" ] || { echo ".agents/skills 가 없습니다: $src" >&2; exit 1; }
mkdir -p "$dst"

# 기존 복사본(스킬 폴더)만 비운다. .gitkeep 등 파일은 남긴다.
find "$dst" -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} +

# .agents/skills 의 스킬 폴더(하위 디렉터리)만 미러링한다. README.md 등 파일은 복사하지 않는다.
count=0
while IFS= read -r -d '' d; do
  cp -R "$d" "$dst/"
  count=$((count + 1))
done < <(find "$src" -mindepth 1 -maxdepth 1 -type d -print0)

echo "동기화 완료: ${count} 개 스킬 (.agents/skills -> .claude/skills)"
