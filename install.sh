#!/usr/bin/env bash
# install.sh — symlink every skill in this repo into a CLI's skills directory.
#
# Works for both Claude Code (~/.claude/skills/) and Grok Build (~/.grok/skills/).
# Grok Build also reads ~/.claude/skills/ for compatibility, but dedupes skills by
# NAME with ~/.grok/skills/ taking priority. So a skill that ships a Grok-native
# variant (SKILL.grok.md) installs into ~/.grok/skills/ to override the Claude one
# in that environment, while Claude-only skills live in ~/.claude/skills/ and are
# still visible to Grok via compatibility.
#
# Idempotent: safe to re-run after `git pull` to pick up new skills.
# Refuses to overwrite an existing real directory at a symlink target;
# replaces existing symlinks pointing elsewhere only after confirmation.
#
# Usage:
#   ./install.sh                       # both targets, every skill
#   ./install.sh --target claude       # only ~/.claude/skills/
#   ./install.sh --target grok         # only ~/.grok/skills/ (Grok-native variants)
#   ./install.sh --target both         # default
#   ./install.sh --dry-run             # show what would happen, do nothing
#   ./install.sh debate                # only the named skill(s)
#   ./install.sh --target grok debate  # combine flags + names

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
GROK_SKILLS_DIR="${GROK_SKILLS_DIR:-$HOME/.grok/skills}"
TARGET="both"
DRY_RUN=0

# --- parse flags (order-independent) ---
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --target=*) TARGET="${1#*=}"; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

case "$TARGET" in
  claude|grok|both) ;;
  *) echo "install.sh: --target must be claude, grok, or both (got '$TARGET')" >&2; exit 1 ;;
esac

# --- determine which skills to install ---
if [[ ${#ARGS[@]} -gt 0 ]]; then
  SKILLS=("${ARGS[@]}")
else
  SKILLS=()
  for d in "$REPO_ROOT"/*/; do
    name="$(basename "$d")"
    [[ -f "$d/SKILL.md" || -f "$d/SKILL.grok.md" ]] && SKILLS+=("$name")
  done
fi

if [[ ${#SKILLS[@]} -eq 0 ]]; then
  echo "install.sh: no skills found (nothing with SKILL.md / SKILL.grok.md at top level)." >&2
  exit 1
fi

run() {
  if [[ $DRY_RUN -eq 1 ]]; then echo "[dry-run] $*"; else "$@"; fi
}

# link SRC -> DST, honoring the "don't clobber real dirs / confirm relinks" policy.
link() {
  local src="$1" dst="$2" label="$3"
  if [[ -L "$dst" ]]; then
    local current; current="$(readlink "$dst")"
    if [[ "$current" == "$src" ]]; then
      echo "  ok   $label (already linked)"
    else
      local ans=""
      if [[ -t 0 ]]; then
        # interactive: ask before replacing a symlink pointing elsewhere
        read -p "  $label: existing symlink -> $current — replace with $src? [y/N] " ans || ans=""
      fi
      if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
        run rm "$dst"; run ln -s "$src" "$dst"; echo "  ok   $label (relinked)"
      else
        echo "  skip $label (kept existing link -> $current; re-run interactively to replace)"
      fi
    fi
  elif [[ -e "$dst" ]]; then
    echo "  skip $label — $dst exists and is not a symlink (refusing to overwrite)" >&2
  else
    run ln -s "$src" "$dst"; echo "  ok   $label (linked)"
  fi
}

chmod_scripts() {
  local src="$1"
  [[ -d "$src/scripts" ]] || return 0
  while IFS= read -r f; do run chmod +x "$f"; done \
    < <(find "$src/scripts" -type f \( -name '*.py' -o -name '*.sh' \))
}

install_claude() {
  local name="$1" src="$REPO_ROOT/$1"
  [[ -f "$src/SKILL.md" ]] || { echo "  skip $name (claude) — no SKILL.md"; return 0; }
  run mkdir -p "$CLAUDE_SKILLS_DIR"
  link "$src" "$CLAUDE_SKILLS_DIR/$name" "$name [claude]"
  chmod_scripts "$src"
}

install_grok() {
  local name="$1" src="$REPO_ROOT/$1"
  if [[ -f "$src/SKILL.grok.md" ]]; then
    # Grok-native variant: install just the renamed SKILL.md into ~/.grok/skills/<name>/.
    run mkdir -p "$GROK_SKILLS_DIR/$name"
    link "$src/SKILL.grok.md" "$GROK_SKILLS_DIR/$name/SKILL.md" "$name [grok-native]"
  else
    echo "  --   $name (grok) — no SKILL.grok.md; Grok reads it from ~/.claude/skills/ via compatibility"
  fi
  chmod_scripts "$src"
}

echo "install.sh: target=$TARGET  claude=$CLAUDE_SKILLS_DIR  grok=$GROK_SKILLS_DIR"
for name in "${SKILLS[@]}"; do
  src="$REPO_ROOT/$name"
  if [[ ! -f "$src/SKILL.md" && ! -f "$src/SKILL.grok.md" ]]; then
    echo "  skip $name — no SKILL.md or SKILL.grok.md at $src" >&2
    continue
  fi
  [[ "$TARGET" == "claude" || "$TARGET" == "both" ]] && install_claude "$name"
  [[ "$TARGET" == "grok"   || "$TARGET" == "both" ]] && install_grok "$name"
done

echo
echo "Done. Restart any running 'claude' / 'grok' session — skills are loaded at session start."
