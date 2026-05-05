---
name: skill-postmortem
description: "Use when an existing user-level Claude Code skill has misbehaved during real use, or when a skill should be reviewed against actual session evidence before being shared more widely. Invoke as `skill-postmortem` (no namespace prefix)."
---

# skill-postmortem

Review a skill against the sessions where it was actually invoked. Surface friction with confidence ranking, propose specific edits, apply only the ones the user approves, commit, push.

## When to use

- A skill misbehaved during real use and you want to know why
- A skill has been invoked multiple times and warrants a structured review
- Suspect a skill's `description` is misfiring (firing on wrong prompts, missing right prompts)
- Cleaning up a skill before publishing more widely

## When NOT to use

- Skill has fewer than 2–3 real invocations — not enough evidence; cold postmortems generate noise
- You already know the exact edit — go straight to editing the SKILL.md
- Plugin-namespaced skill (`<plugin>:<name>`) — its source lives upstream; edit there and PR back, don't fork-and-edit locally
- The "friction" is user-side environment drift (e.g. an upstream tool was upgraded and broke the skill) — pin or version-detect, don't mutate the skill on every external change

## Preflight

1. **Target skill resolves.** Skill name supplied; `~/.claude/skills/<name>/SKILL.md` exists (follow symlinks). If plugin-namespaced, abort: "this skill targets user-level skills only."
2. **Source dir is a git repo.** `git -C $(readlink -f ~/.claude/skills/<name>)/.. rev-parse --is-inside-work-tree`. If not, postmortem can produce edits but can't commit them — warn and continue read-only.
3. **JSONL projects dir exists.** `~/.claude/projects/`. If empty, no evidence — abort cleanly.

## Phase 1 — Gather evidence

Find every recent session JSONL that mentions the target skill:

```bash
SKILL_NAME=<name>
grep -l "\"$SKILL_NAME\"" ~/.claude/projects/*/*.jsonl 2>/dev/null \
  | xargs -I{} ls -la {} \
  | sort -k6,7 \
  | tail -30
```

Read the 30 most recent matches. For each, extract the **conversation slice** around the skill invocation: the firing turn, the next 5–10 assistant turns, plus tool errors and user corrections within that window.

Skip noise:
- Sessions where the skill name appears only in the skill list and was never invoked
- Sessions abandoned with `/clear` and no actionable signal

State up front: "Found N sessions invoking `<skill>`, taking M most recent for analysis."

## Phase 2 — Categorize friction

Classify every signal into one of the following. Each row also lists the symptom that identifies it.

| Code | Category | Symptom |
|------|----------|---------|
| A | Spec gap | Claude asked a clarifying question the skill should have answered, or invented an answer (visible from later user correction) |
| B | Wrong CLI / API shape | Tool errors with messages like "Unknown action," "command not found," "invalid_params"; or the user typing the right command shape and saying "use this instead" |
| C | Trigger phrase miss | The user described a situation the skill should handle, but Claude didn't invoke — or invoked the wrong one (often a namespaced sibling) |
| D | Scope ambiguity | Claude did too much (touched out-of-scope files) or too little (stopped where it should have continued); user redirected |
| E | Hardcoded assumption | Bundled scripts failed on the user's actual environment (path with spaces, OS difference, tool version) where a regex/glob/command made an over-narrow assumption |
| F | Manual workaround | The user (or Claude) bypassed the skill's bundled scripts and wrote inline code instead, often because the script had a known issue |
| G | Preflight too strict / too loose | Aborts on cases that should run, or runs past cases it should catch |
| H | Description-trigger collision | Skill fired when it shouldn't, or didn't fire when it should |

## Phase 3 — Confidence-rank

| Confidence | Criteria | Action |
|------------|----------|--------|
| **High** | Same friction in 2+ separate sessions, OR single session with explicit user feedback typing the corrected shape | Propose an edit |
| **Medium** | Single session, single occurrence, but the failure is concrete (specific error message, not vibes) | Surface as a question to the user, no diff |
| **Low** | One-off Claude misread without a smoking gun | Watch list only — do not propose edits |

State counts per category and band before proposing edits:

```
Friction found across N sessions:
  Category B (wrong CLI shape):      2 high, 1 medium
  Category E (hardcoded assumption): 1 high
  Category F (manual workaround):    1 high, 2 medium
Total: 4 high-confidence edits proposed.
       3 medium-confidence flagged for user judgment.
```

## Phase 4 — Propose edits

For each high-confidence finding:

1. **Finding** — one sentence on what was wrong
2. **Evidence** — 1–3 quoted lines from session JSONLs (filename + approximate turn)
3. **Proposed edit** — diff against the relevant file (`SKILL.md`, `scripts/<x>.py`, `references/<y>.md`)
4. **Why this edit, not a bigger one** — explain scope. Resist the urge to refactor.

For medium-confidence: phrase as questions to the user, not diffs.

## Phase 5 — Apply

Show all proposed edits as one block. Ask: "Apply edits 1, 3, 5? Skip 2 and 4? Pick a subset?" Wait for explicit confirmation.

Per approved edit:

1. Apply diff with the `Edit` tool
2. Run any verification the skill supports (typecheck, `python3 -m py_compile`, etc.)
3. Stage the change

After all approved edits land, one commit per category:

```
fix(<skill-name>): <one-line summary of category>

<paragraph: what was wrong, what evidence supported the change, what the
edit specifically does. Reference session JSONL filenames where useful.>
```

Push. Surface the commit URL.

If the source dir isn't a git repo (preflight #2 warned), surface the diffs as text the user can apply manually.

## Anti-patterns

- **Generic advice** — "be careful with X" or "consider Y" added to a skill's body without a specific scenario and evidence is not actionable
- **Restating defaults** — skills shouldn't be the manual; if a tool's `--help` covers it, link, don't paste
- **Editing low-confidence signals** — if it appeared once with no explicit user correction, leave it; wait for it to recur
- **Over-fitting to one user's environment** — if the user's `cmux` has command set X but a teammate's older `cmux` has Y, an edit that hardcodes X breaks the teammate; add an environment check or document the version
- **Refactoring beyond the finding** — postmortem mandate is "fix what evidence supports"; code style you don't like is a separate task

## Common mistakes

| ❌ Wrong | ✅ Right |
|---------|---------|
| Run on a skill with one or zero sessions of evidence | Wait for at least 2–3 invocations; cold postmortems generate noise |
| Edit based on what you think the skill *should* say | Edit only on what evidence in JSONLs *demonstrates* the skill needs |
| One giant commit with all changes | One commit per category — easier to revert if wrong |
| Skip the evidence-quote step | Always quote the JSONL line motivating the edit, with filename — future postmortems can cross-reference |
| Surface every signal at every confidence | Edit only high-confidence; medium becomes user-questions; low stays as a watch list |
| Apply edits without re-running verification | If the skill bundles `scripts/x.py`, `python3 -m py_compile` after editing |
| Forget to push after commit | Always push — the canonical skill is on GitHub for `git pull` updates |

## Checklist

Before declaring the postmortem done:

- [ ] Identified target skill and resolved its source directory
- [ ] Found N sessions of evidence (state N)
- [ ] Categorized every friction signal across A–H
- [ ] Confidence-ranked each
- [ ] Proposed only high-confidence edits with quoted evidence
- [ ] Got explicit user approval before applying
- [ ] Verified scripts compile / typecheck where applicable
- [ ] Committed per category, with evidence cited in the message
- [ ] Pushed
