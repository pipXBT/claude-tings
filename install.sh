#!/usr/bin/env bash
# install.sh — symlink every skill in this repo into ~/.claude/skills/.
#
# Idempotent: safe to re-run after `git pull` to pick up new skills.
# Refuses to overwrite an existing real directory at the symlink target;
# replaces existing symlinks pointing elsewhere only after confirmation.
#
# Usage:
#   ./install.sh                 # symlink every skill subdir found
#   ./install.sh --dry-run       # show what would happen, do nothing
#   ./install.sh skill-name ...  # only the named skills

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

# Determine which skills to install.
if [[ $# -gt 0 ]]; then
  SKILLS=("$@")
else
  # Every top-level dir that contains a SKILL.md is a skill.
  SKILLS=()
  for d in "$REPO_ROOT"/*/; do
    name="$(basename "$d")"
    if [[ -f "$d/SKILL.md" ]]; then
      SKILLS+=("$name")
    fi
  done
fi

if [[ ${#SKILLS[@]} -eq 0 ]]; then
  echo "install.sh: no skills found (nothing with SKILL.md at top level)." >&2
  exit 1
fi

mkdir -p "$SKILLS_DIR"

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo "install.sh: target = $SKILLS_DIR"
for name in "${SKILLS[@]}"; do
  src="$REPO_ROOT/$name"
  dst="$SKILLS_DIR/$name"

  if [[ ! -f "$src/SKILL.md" ]]; then
    echo "  skip $name — no SKILL.md at $src" >&2
    continue
  fi

  if [[ -L "$dst" ]]; then
    current="$(readlink "$dst")"
    if [[ "$current" == "$src" ]]; then
      echo "  ok   $name (already linked)"
    else
      read -p "  $name: existing symlink points to $current — replace with $src? [y/N] " ans
      if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
        run rm "$dst"
        run ln -s "$src" "$dst"
        echo "  ok   $name (relinked)"
      else
        echo "  skip $name (kept existing link)"
      fi
    fi
  elif [[ -e "$dst" ]]; then
    echo "  skip $name — $dst exists and is not a symlink (refusing to overwrite)" >&2
  else
    run ln -s "$src" "$dst"
    echo "  ok   $name (linked)"
  fi

  # chmod any bundled scripts
  if [[ -d "$src/scripts" ]]; then
    while IFS= read -r f; do
      run chmod +x "$f"
    done < <(find "$src/scripts" -type f \( -name '*.py' -o -name '*.sh' \))
  fi
done

echo
echo "Done. Restart any running 'claude' session — skills are loaded at session start."
