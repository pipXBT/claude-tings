---
name: skill-postmortem
description: "Use to review the effectiveness of an existing Claude Code skill and propose evidence-backed edits to its SKILL.md, scripts, or references. Reads recent session JSONLs where the skill was invoked, extracts friction signals (tool errors, user corrections, abandoned invocations, manual workarounds), confidence-ranks them, and proposes specific edits with diffs. User approves each edit before it lands. Triggers: 'review skill X', 'postmortem skill X', 'why did skill X fail', 'iterate on skill X', 'update skill X based on usage', 'what's wrong with skill X', 'skill review', 'skill effectiveness', or any time the user says a skill misbehaved and wants it improved. INVOCATION: this is a user-level skill installed at ~/.claude/skills/skill-postmortem/. Invoke with Skill(skill=\"skill-postmortem\") — bare name, NO namespace prefix. Not part of the superpowers, figma, or any other plugin."
---

# skill-postmortem

Review a skill against the actual sessions where it was invoked, surface friction with confidence ranking, propose specific edits, apply the ones the user approves, commit + push.

Borrows the **watch → categorize → apply → anti-patterns** methodology from STRML's [`session-learnings`](https://github.com/STRML/cc-skills/blob/main/skills/session-learnings/SKILL.md). The new pieces: cross-session evidence (rather than just current session), explicit confidence ranking (because the same friction across 3 sessions is much stronger signal than 1), and the target is the skill's own files instead of project `CLAUDE.md`.

**Design choice — why user-in-the-loop, not auto-apply.** "Self-learning skills" sounds good but is a footgun: a skill that auto-edits itself based on transcript heuristics will accumulate fixes that look local but compound into incoherent direction. The defensible shape is *evidence-ranked proposals + explicit user approval*. The skill does the gathering and analysis (the boring part); the user does the decision (the part that needs judgment).

## Preflight

1. **Target skill resolves.** Skill name supplied; `~/.claude/skills/<name>/SKILL.md` exists (follow symlinks). If it's a plugin skill (`<plugin>:<name>`), the source lives under `~/.claude/plugins/<plugin>/skills/<name>/` — abort with "this skill targets user-level skills only; for plugin skills, edit upstream and PR back."
2. **Source dir is a git repo.** `git -C $(readlink -f ~/.claude/skills/<name>)/.. rev-parse --is-inside-work-tree`. If not, the postmortem can produce edits but can't commit them — warn and continue read-only.
3. **JSONL projects dir exists.** `~/.claude/projects/`. If empty, no evidence — abort cleanly.

If preflight fails, surface which check and stop.

## Phase 1 — Gather evidence

Locate every recent session JSONL that mentions the target skill. The skill name appears in transcripts when:
- Claude invokes it via the `Skill` tool (`Skill(skill="<name>")`)
- The system-reminder skill list is included (skills appear in their own paragraph)
- The user references it by name in a message

Use `recall` (STRML skill) if available, otherwise:

```bash
SKILL_NAME=<name>
grep -l "\"$SKILL_NAME\"" ~/.claude/projects/*/*.jsonl 2>/dev/null \
  | xargs -I{} ls -la {} \
  | sort -k6,7 \
  | tail -30
```

Read the 30 most recent matching JSONLs. For each, extract the **conversation slice** around the skill invocation (the turn that fired it, the next 5–10 assistant turns, plus any tool errors and user corrections within that window).

Skip noise:
- Sessions where the skill name only appears in the system-reminder skill list and was never invoked.
- Sessions where the invocation was immediately followed by `/clear` or session abandonment with no signal.

State up front: "Found N sessions invoking `<skill>`, taking the M most recent for analysis."

## Phase 2 — Extract friction signals

For each session slice, classify what happened. Categories below are adapted from STRML's session-learnings buckets, retargeted at skills:

### A. Spec gaps
The skill's instructions don't tell Claude what to do in some situation it hit. Symptoms: Claude asks the user a clarifying question that the skill *should* have answered, or invents an answer (visible from a later user correction).

### B. Wrong CLI / API shape
The skill calls a command/argument that doesn't exist or has different syntax. Symptoms: tool errors with messages like "Unknown tab action," "command not found," "invalid_params," or the user typing the right command shape and saying "use this instead."

Example from `parallel-orchestrate` testing: the skill instructs `cmux close-workspace` but the actual cmux CLI doesn't have a workspace-close command in that shape; the user discovered `cmux tab-action --action close` also fails (`close` is not a valid action).

### C. Trigger phrase miss
The user described a situation the skill should handle, but Claude didn't invoke the skill — or invoked the wrong one (e.g., a namespaced sibling). Symptoms: "no, use the X skill" corrections, or the user explicitly typing the skill name after Claude failed to find it.

### D. Scope ambiguity
The skill's mandate is unclear about what's in/out of scope. Symptoms: Claude doing too much (touching files outside the apparent scope) or too little (stopping where the skill should have continued), and the user redirecting.

### E. Hardcoded assumption
The skill assumes a config/path/tool/version that varies. Symptoms: scripts failing on the user's actual environment (path with spaces, different shell, different OS, different cmux version, etc.) where the regex/glob/command made an over-narrow assumption.

Example from `parallel-orchestrate` testing: `encode_project_path()` only replaces `/` and `.` with `-`, but Claude Code's actual encoding also replaces spaces. Project paths with spaces silently end up at the wrong directory.

### F. Manual workaround
The user (or Claude) bypassed the skill's bundled scripts and wrote inline code instead. Symptoms: an inline Bash/Python block doing what `scripts/<x>.py` is supposed to do, often because the script had a known issue or the wrong shape.

### G. Preflight too strict / too loose
Preflight aborts in cases that should have continued, OR it lets through cases that later fail. Symptoms: user typing "skip preflight" or commenting out a check, OR the skill running past a missing dependency it should have caught.

### H. Description-trigger collisions
The skill's `description` triggers on phrases that fire it inappropriately, or fails to trigger on phrases that should fire it. Symptoms: skill invoked when user wanted something else, or user repeating themselves after the wrong skill ran.

## Phase 3 — Confidence-rank

For every signal, score:

| Confidence | Criteria |
|------------|----------|
| **High**   | Same friction appears in **2+ separate sessions**, OR a single session contains explicit user feedback ("don't do X, do Y") with the user typing the corrected shape. Edit is almost certainly correct. |
| **Medium** | Single session, single occurrence, but the failure mode is concrete (tool error with a specific error message, not vibes). Edit likely correct but worth confirming. |
| **Low**    | One-off Claude misread without a clear smoking gun. Probably skill is fine; Claude's interpretation drifted that turn. **Do not propose an edit at this confidence — surface as a "watch" item only.** |

State the count per category and per confidence band before proposing edits. Example:

```
Friction found across 7 sessions:
  Category B (wrong CLI shape):      2 high, 1 medium
  Category E (hardcoded assumption): 1 high, 0 medium
  Category F (manual workaround):    1 high, 2 medium
  Category H (description trigger):  0 high, 1 medium

Total: 4 high-confidence findings recommended for edit.
       3 medium-confidence findings flagged for user judgment.
       Other categories: no signal.
```

## Phase 4 — Propose edits

For each high-confidence finding, draft a *specific* edit. Show:

1. **Finding** — one sentence on what was wrong.
2. **Evidence** — 1–3 quoted lines from session JSONLs (filename + approx turn).
3. **Proposed edit** — diff against the relevant file (`SKILL.md`, `scripts/x.py`, `references/y.md`).
4. **Why this edit, not a bigger one** — explain scope. Resist the urge to refactor.

Example (drawn from real findings on `parallel-orchestrate`):

```
Finding: encode_project_path doesn't handle paths with spaces.
Category: E (hardcoded assumption), Confidence: high
Evidence: session 6afdc4dd-e2c2-... — fork landed JSONL at wrong dir;
          encode regex only replaces / and ., not spaces.

Proposed edit (scripts/spawn-cmux.py):
- def encode_project_path(p: Path) -> str:
-     return re.sub(r"[/.]", "-", str(p.resolve()))
+ def encode_project_path(p: Path) -> str:
+     return re.sub(r"[^A-Za-z0-9]", "-", str(p.resolve()))

Why not bigger: matches Claude Code's actual encoding (any non-alphanumeric
becomes -). Single-character regex change, no behaviour change for paths
that already worked.
```

For medium-confidence findings, flag but don't draft a diff — phrase them as *questions to the user* ("Saw X once; is this a recurring issue or a one-off?").

## Phase 5 — User approves, apply, commit

Show all proposed edits as one block. Ask: "Apply edits 1, 3, 5? Skip 2 and 4? Or pick a subset?" Wait for explicit confirmation.

Then per approved edit:
1. Apply the diff with the `Edit` tool.
2. Run any verification the skill supports (typecheck, `python3 -m py_compile`, etc.).
3. Stage the change.

After all approved edits land, one commit per category (or one combined commit if small):

```
fix(skill-name): <one-line summary of category>

<paragraph: what was wrong, what evidence supported the change, what the
edit specifically does. Reference the session JSONL filenames if useful.>
```

Push. State commit URL.

If the source dir isn't a git repo (preflight #2 warned), surface the diffs as text the user can apply manually instead.

## Anti-patterns

Direct lifts from STRML's session-learnings, retargeted:

- **Generic advice** — don't add "be careful with X" or "consider Y" to a skill's body. If you can't pin the issue to a specific scenario with evidence, it's not actionable.
- **Obvious things** — don't document standard tool behaviour (e.g. "git push requires a remote"). Skills shouldn't restate the manual.
- **Temporary info** — don't add session-specific findings (the user's project paths, today's branch names) to the skill. Skills are reusable; if it's only true today, it goes in CLAUDE.md or memory, not the skill.
- **Duplicating docs** — don't paste in a tool's `--help` output. Reference the tool, link the docs, move on.

Plus skill-postmortem-specific anti-patterns:

- **Editing low-confidence signals** — if it appeared once, with no explicit user correction, leave it. Wait for it to recur. Premature edits accumulate noise; coherent skills have fewer, sharper rules.
- **Over-fitting to one user's environment** — if the user's `cmux` is on commit X with that command set, but a teammate's `cmux` is older and has a different shape, your edit can't hardcode the user's. Add an environment check or document the version, don't bake the assumption in.
- **Refactoring beyond the finding** — the postmortem's mandate is "fix what evidence supports." If you also see code style you don't like, leave it. That's a separate task with separate confirmation.

## Common mistakes

| ❌ Wrong | ✅ Right |
|---------|---------|
| Run on a skill with one or zero sessions of evidence | Wait for at least 2–3 invocations; cold postmortems generate noise |
| Edit based on what you think the skill *should* say | Edit only on what evidence in JSONLs *demonstrates* the skill needs |
| One giant commit with all changes | One commit per category (B-fixes vs E-fixes vs H-fixes) — easier to revert if wrong |
| Skip the evidence-quote step | Always quote the exact JSONL line that motivated the edit, with filename — future postmortems can cross-reference |
| Surface every signal at every confidence | Edit only high-confidence; medium becomes user-questions; low stays as a watch list |
| Apply edits without re-running verification (where applicable) | If the skill bundles `scripts/x.py`, `python3 -m py_compile` it after editing |
| Forget to push after commit | Always push — the canonical skill is on GitHub for `git pull` updates |

## When NOT to use this skill

- **Skill is brand-new with <2 invocations.** Wait until you have evidence; cold postmortems generate noise.
- **You already know the fix and just want to apply it.** Skip straight to `superpowers:writing-skills`.
- **Plugin-namespaced skill (`<plugin>:<name>`).** Source lives in `~/.claude/plugins/<plugin>/skills/<name>/` — edit upstream and open a PR; don't fork-and-edit locally.
- **The "friction" is actually user-side configuration drift.** If `cmux` was upgraded and broke the skill, the fix is to pin or version-detect, not to mutate the skill on every upgrade.

## Checklist (lifted from session-learnings, adapted)

Before declaring the postmortem done:

- [ ] Identified target skill and resolved its source directory
- [ ] Found N sessions of evidence (state N)
- [ ] Categorized every friction signal (A–H)
- [ ] Confidence-ranked each
- [ ] Proposed only high-confidence edits with quoted evidence
- [ ] Got explicit user approval before applying
- [ ] Verified scripts compile / typecheck where applicable
- [ ] Committed per category, with evidence cited in the message
- [ ] Pushed

## Credits

Methodology — watch → categorize → apply → anti-patterns → checklist — adapted from [STRML/cc-skills/skills/session-learnings](https://github.com/STRML/cc-skills/blob/main/skills/session-learnings/SKILL.md). Building blocks: [`recall`](https://github.com/STRML/cc-skills/blob/main/skills/recall/SKILL.md) for finding sessions, [`superpowers:writing-skills`](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) for the actual editing patterns, [`superpowers:verification-before-completion`](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) for the don't-claim-done-without-evidence discipline.
