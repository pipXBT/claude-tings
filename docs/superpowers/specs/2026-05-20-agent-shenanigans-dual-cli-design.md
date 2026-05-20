# agent-shenanigans — dual-CLI skills repo (design)

**Date:** 2026-05-20
**Status:** approved, implemented

## Goal

Rename the `claude-tings` skills repo to `agent-shenanigans`, add the personal
`debate` skill, and make the repo usable from both **Claude Code** and **Grok Build**.

## Key facts driving the design

- `/debate:all` is not a standalone skill — it is one command in STRML's `cc-debate`
  plugin, dependent on `~/.claude/debate-scripts/*.sh`, `~/.claude/debate-acpx.json`,
  sibling commands, and the external `acpx` CLI. What this repo vendors is the user's
  **surfacing skill** (`~/cc-skills/skills/debate/SKILL.md`) plus a **Grok-native port**
  (`~/.grok/skills/debate/SKILL.md`) and the user's personalized reviewer panel.
- Grok Build discovers skills from `./.grok/skills/`, `<repo>/.grok/skills/`,
  `~/.grok/skills/`, **and `~/.claude/skills/`** (compatibility), deduping by skill
  *name* with that priority order (`~/.grok/` beats `~/.claude/`).
- Both CLIs use the same `SKILL.md` directory contract.

## Design

### Rename
- Local dir `claude-tings` → `agent-shenanigans`.
- GitHub `pipXBT/claude-tings` → `pipXBT/agent-shenanigans` via `gh repo rename`
  (old URL auto-redirects); update `origin`.
- Update in-file references (README title, clone URLs).

### The `debate` skill — two variants in one dir
```
debate/
├── SKILL.md                  # Claude Code (acpx + external CLIs) → ~/.claude/skills/debate/
├── SKILL.grok.md             # Grok Build native (spawn_subagent) → ~/.grok/skills/debate/SKILL.md
└── debate-acpx.example.json  # personalized panel: Skeptic/Architect/Pragmatist + Grok personas
```
The dedup-by-name priority means Claude Code sees the acpx variant and Grok Build sees
the native one, with no name collision. README + SKILL.md credit STRML's `cc-debate`.

### Cross-tool plumbing (AGENTS.md standard)
- Root `AGENTS.md` = cross-tool agent guide (Grok reads it natively as project rules).
- `CLAUDE.md` → symlink to `AGENTS.md` so Claude Code reads the same.
- `install.sh` gains `--target claude|grok|both` (default `both`):
  - claude: symlink each skill dir → `~/.claude/skills/<name>`.
  - grok: any skill with a `SKILL.grok.md` → `~/.grok/skills/<name>/SKILL.md`; skills
    without one are noted as already visible via `~/.claude/skills/` compatibility.

### Scope boundary
`parallel-orchestrate` and `skill-postmortem` stay Claude-oriented (install to
`~/.claude/skills/`, visible to Grok via compatibility, not ported to Grok primitives).
Only `debate` gets a true dual-variant treatment.

## Out of scope
- Porting `parallel-orchestrate` / `skill-postmortem` to Grok primitives.
- Publishing `debate` as a packaged plugin (it stays a vendored skill).
