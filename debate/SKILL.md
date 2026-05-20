---
name: debate
description: "Use for multi-AI plan review before writing code. Get second opinions from Codex, Gemini, Opus, DeepSeek, etc. Triggers: 'debate the plan', 'multi-model review', 'run debate', 'get reviewer feedback', 'second opinion on this approach', '/debate:all'."
---

# Debate — Multi-AI Plan Review

Before implementing any non-trivial plan, send it to a panel of independent AI reviewers (Codex, Gemini, Claude Opus, Mercury, DeepSeek, etc.) running in parallel. They surface hidden assumptions, failure modes, and structural issues, debate contradictions, and produce a consensus verdict (APPROVED / REVISE).

This is the highest-leverage quality gate in the toolkit. Use it on design specs, implementation plans, architecture changes, and any work where "I wish I had caught that earlier" is a risk.

## Prerequisites (one-time)

```bash
# 1. acpx (unified agent protocol client)
npm install -g acpx@latest

# 2. jq (required by scripts)
brew install jq   # macOS
```

## Initial Setup

```bash
# Interactive reviewer configuration (recommended)
/debate:acpx-setup
```

This walks you through:
- Detecting installed agent CLIs (codex, gemini, opencode, etc.)
- Creating OpenRouter/LiteLLM agents for models not natively supported
- Probing connectivity
- Generating a starter `~/.claude/debate-acpx.json`

## Config (`~/.claude/debate-acpx.json`)

Reviewers are defined here. Example with three local Opus personas:

```json
{
  "reviewers": {
    "skeptic": {
      "agent": "opus",
      "timeout": 240,
      "system_prompt": "You are The Skeptic. ..."
    },
    "architect": { ... },
    "pragmatist": { ... }
  }
}
```

Mix and match any acpx-supported agents: `codex`, `gemini`, `claude`, `opencode`, custom OpenRouter models (DeepSeek R1, Mercury, Kimi, etc.), LiteLLM local models, etc.

See `/debate:acpx-setup` output for the current panel and any missing auth.

## Usage

### Full multi-model debate (recommended)

```bash
/debate:all
```

- Runs all reviewers in `~/.claude/debate-acpx.json` in parallel
- Includes a parallel Claude Opus "claude-skeptic" subagent
- Synthesizes findings, runs a targeted debate phase on contradictions
- Up to 3 revision rounds + verification passes
- Final consensus verdict with SHA-verified plan

Options:
- `/debate:all codex,gemini` — run only specific reviewers
- `/debate:all skip-debate` — straight to final report, no debate round

### Lighter Claude-only reviews

- `/debate:claude-review` — single Opus skeptic (up to 5 rounds)
- `/debate:claude-double-review` — Skeptic + Architect in parallel
- `/debate:claude-custom-review` — interactive personality + model picker

### Setup & diagnostics

- `/debate:setup` — print permission allowlist for unattended use, verify symlinks
- `/debate:acpx-setup` — interactive config + connectivity probe (run this first)

## Unattended / No-prompt mode

After first use, add the printed Bash/Read/Write/Agent patterns to your `~/.claude/settings.json` `"permissions"."allow"` array so future debates never ask for approval.

`/debate:setup` prints the exact snippet with your real paths.

## When to reach for this

- Any plan > 1 page or touching > 2 subsystems
- Before a "wave" of implementation work
- After a major spec change
- When the cost of a bad assumption is high (auth, money, data loss, security)

## Notes

- The actual command implementations live in the `cc-debate` plugin (installed via `/plugin install debate@cc-debate`). This skill exists to surface the capability in every session's skill list.
- A ready-to-use reviewer panel ships alongside this skill at `debate/debate-acpx.example.json` (Skeptic / Architect / Pragmatist plus the Grok personas Bullshit Detector, Constraint Engineer, Pager Duty, Future Me). Copy it to `~/.claude/debate-acpx.json` to skip the interactive setup.
- All reviewer output is read in full (no skimming). SHA checks prevent "I fixed it, trust me" bypasses.
- Work dirs are in `.tmp/ai-review-*` inside the project and cleaned up automatically (or via `safe-cleanup.sh`).
- Gemini requires a `GEMINI_API_KEY` in `~/.claude/settings.json` env (OAuth token does not work in acpx subprocess mode).

Run `/debate:acpx-setup` if you haven't configured reviewers yet.

---

**Grok users:** There is a native Grok Build port of this skill, vendored alongside this file as `debate/SKILL.grok.md` (installed to `~/.grok/skills/debate/SKILL.md` by `install.sh --target grok`). It uses the same philosophy (personas, parallel subagents, debate rounds, SHA gates) but is implemented with Grok's `spawn_subagent` + `resume_from` + `todo_write` primitives instead of acpx + external CLIs. Grok Build also reads `~/.claude/skills/`, but dedupes skills by name with `~/.grok/skills/` taking priority — so installing both variants gives each environment the right one automatically. The two versions are complementary.

---

*Inspired by Sam Reed's ([STRML](https://github.com/STRML)) [`cc-debate`](https://github.com/STRML/cc-debate) plugin and [`cc-skills`](https://github.com/STRML/cc-skills). This is a personal adaptation; the upstream plugin remains the canonical implementation of the `/debate:*` commands.*
