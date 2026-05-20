# agent-shenanigans — guide for AI agents

This repository is a **personal collection of agent skills** that work in both
**Claude Code** and **Grok Build**. If you are an AI agent working *in this repo*,
read this first. (This file follows the cross-tool `AGENTS.md` convention; Grok
Build loads it natively as project rules, and Claude Code reads it via the
`CLAUDE.md` symlink that points here.)

## What this repo is

Each top-level directory is one self-contained skill: a `SKILL.md` (YAML
frontmatter + markdown instructions) plus any scripts/reference docs it needs.
Skills are distributed by symlinking them into a CLI's skills directory, not by
copying — so `git pull` propagates updates instantly.

## The two-CLI model (important)

Both CLIs read `SKILL.md`-shaped skill directories, but from different roots:

| CLI         | User skills dir      | Also reads          |
|-------------|----------------------|---------------------|
| Claude Code | `~/.claude/skills/`  | —                   |
| Grok Build  | `~/.grok/skills/`    | `~/.claude/skills/` |

Grok Build dedupes skills **by name**, with `~/.grok/skills/` taking priority
over `~/.claude/skills/`. We exploit this for skills that need different
implementations per environment:

- `SKILL.md` in a skill dir → the **Claude Code** variant (installed to `~/.claude/skills/<name>/`).
- `SKILL.grok.md` in the same dir → the **Grok-native** variant (installed to `~/.grok/skills/<name>/SKILL.md`).

Result: Claude Code sees only its variant; Grok Build sees both but the
`~/.grok/` one wins. One skill name, two environments, no collision.

A skill with **only** a `SKILL.md` (no `.grok` variant) is environment-agnostic:
it installs to `~/.claude/skills/` and Grok picks it up there via compatibility.

## Adding or editing a skill

1. Create `<skill-name>/SKILL.md` with frontmatter:
   ```markdown
   ---
   name: my-skill
   description: "Use when ... [trigger phrases]. [What it does, one sentence.]"
   ---
   ```
   The `description` is the trigger surface for both CLIs — pack it with concrete
   trigger phrases and a clear use-case statement.
2. If the skill needs different behavior in Grok Build, add `<skill-name>/SKILL.grok.md`.
3. Put executable helpers in `<skill-name>/scripts/` (chmodded by `install.sh`),
   load-on-demand docs in `<skill-name>/references/`.
4. Add a row to the skills table in `README.md`.
5. Re-run `./install.sh` (or `./install.sh <skill-name>`) to link it.

## Conventions

- Don't relabel third-party work as your own. Skills adapted from someone else's
  plugin must credit the source (see `debate/` → STRML's `cc-debate`).
- Never commit secrets. Reviewer/config examples ship as `*.example.json` with
  prompts and agent names only — no API keys or tokens.
- Keep each skill self-contained and single-purpose; if a `SKILL.md` is doing two
  jobs, split it.
