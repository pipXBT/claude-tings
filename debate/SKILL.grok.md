---
name: debate
description: >
  Grok-native "debate all" / full multi-reviewer plan critique. Runs the complete panel of strong Grok personas (Bullshit Detector, Constraint Engineer, Pager Duty Engineer, Future Me) in parallel on grok-4.3, synthesizes, runs targeted debate rounds on contradictions, and produces a consensus VERDICT with SHA-verified plan. This is the official full "all reviewers" experience inside Grok Build.

  Use for any non-trivial implementation plan, spec, or design.

  Triggers (Grok Build): "debate all", "debate:all", "/debate:all", "run full debate", "multi-review with all Grok reviewers", "full grok debate", "debate this with the complete panel", "run all reviewers".

  Note: This is the pure Grok version. When you are in Claude Code, use the separate acpx-powered `/debate:all` (external models via acpx). This skill is deliberately isolated so the two environments stay independent.
metadata:
  short-description: "Grok's native full-panel 'debate all' — 4 strong personas + synthesis + SHA gates (use this in Grok Build)"
  grok-only: true
  replaces-claude-command: false   # Intentional: /debate:all in Claude still uses the acpx plugin
---

# debate — Grok-Native "Debate All" (Full Multi-Reviewer Plan Critique)

**This is Grok Build's equivalent of `/debate:all`.**  
When you are inside Grok Build and say "debate all", "debate:all", or any of the triggers listed above, this skill runs the complete panel of four powerful Grok personas.

**Environment separation (important):**
- **In Grok Build** → Use this skill (pure Grok subagents on grok-4.3). This is what you want.
- **In Claude Code** → Use the separate acpx version at `/debate:all` (can include Codex, Gemini, Claude Opus, etc.). That version is left completely untouched.

---

## How to invoke "debate all" inside Grok Build

Just say any of these (the skill is designed to recognize them as the full-panel request):

- "debate all"
- "debate:all"
- "/debate:all"
- "run full debate on this plan"
- "multi-review with all Grok reviewers"
- "full grok debate"
- "debate this with the complete panel"
- "run all reviewers"

The skill will automatically:
1. Run **all four** personas in parallel
2. Synthesize
3. Debate contradictions if they appear
4. Apply the SHA verification gate
5. Give you a clear final VERDICT

No extra flags needed — "all reviewers" is the default and only mode.

---

Get a second, third, and fourth opinion from Grok itself wearing different sharp, irreverent, truth-seeking hats before you write a line of code. Fast, context-rich, and fully native to this environment — no external CLIs or acpx required.

## Why this exists

This skill is Grok's native answer to the "debate all" / full multi-reviewer workflow.

The original Claude cc-debate (STRML/cc-debate) is excellent but tied to Claude Code's plugin + acpx + external agent CLIs. This is the direct Grok port: same philosophy (independent personas, parallel execution, targeted debate on disagreements, SHA self-check to prevent "I fixed it in my head" bypasses), reimplemented with Grok's native `spawn_subagent`, `resume_from`, `wait_commands_or_subagents`, `todo_write`, and `fork_context`.

**By default it always runs the full panel** (all four personas in parallel). There is no "lite" mode — this is the complete "debate all" experience inside Grok.

## Core Workflow (what you will do when this skill is active)

1. **Capture the plan** — write it to `.tmp/grok-debate-<id>/plan.md` (or take it from conversation context).
2. **Parallel Round N** — spawn 3–4 reviewers with strong distinct personas. They inherit context via `fork_context: true`.
3. **Collect & Synthesize** — read every full review (no skimming). Categorize unanimous points, unique insights, contradictions.
4. **Targeted Debate** (if contradictions) — resume the conflicting reviewers with each other's exact quotes and ask them to respond / update verdict.
5. **SHA Gate** — before any APPROVED, prove the plan.md the reviewers saw is byte-identical to the current one.
6. **Revision Loop** (max 3 rounds) — if REVISE, you revise the plan, write a diff summary, re-review the changed plan.
7. **Final Report + Cleanup** — clear verdict + actionable concerns. Safe temp dir cleanup.

Use `todo_write` throughout to maintain a live "Review Board" visible to the user.

## Default Reviewers — The Full "All" Panel (always runs all four)

This skill **always** launches the complete set of reviewers in parallel — this is the Grok equivalent of "debate all".

These are deliberately *not* polite corporate reviewer voices. They are Grok wearing different sharp, slightly mean, high-signal hats.

| Reviewer              | Subagent Type     | Focus (Grok-flavored)                                      | Typical Question It Asks |
|-----------------------|-------------------|------------------------------------------------------------|--------------------------|
| Bullshit Detector     | explore           | Vague language, hand-wavy assumptions, "it'll be fine", corporate-speak, things that sound good on paper | "What are we actually claiming here, and why do we believe any of it?" |
| Constraint Engineer   | plan              | Fundamental limits, invariants, physics, information theory, incentive misalignments, what *must* be true | "What law of nature or economics are we violating?" |
| Pager Duty Engineer   | general-purpose   | 3am reality: partial failure, human error, config drift, monitoring gaps, "how do I debug this in the dark with no coffee" | "What wakes someone up and how long until they hate their life?" |
| Future Me             | general-purpose   | Long-term maintainability, cognitive load in 18 months, "will I still understand this when I'm tired and grumpy?" | "Will Future Me send me a thank-you note or a middle finger?" |

You can override the panel via `~/.grok/debate.json` (see Config section).

## Step-by-Step Instructions (when the user asks you to debate)

### 0. Setup Workdir & Todo Board

```bash
REVIEW_ID=$(date +%s | shasum | cut -c1-8)
WORK_DIR="$PWD/.tmp/grok-debate-$REVIEW_ID"
mkdir -p "$WORK_DIR"
```

Immediately create a todo board:

Use the `todo_write` tool with a list containing at least:
- "Capture plan to plan.md"
- "Round 1: Bullshit Detector, Constraint Engineer, Pager Duty Engineer, Future Me (parallel)"
- "Synthesis & contradictions"
- "Debate round (if needed)"
- "SHA verification gate"
- "Final report"

Update the board as you progress.

### 1. Capture the Plan

- If the user just said "debate this" and pasted a plan/spec: write it verbatim to `$WORK_DIR/plan.md`.
- If the plan is in the current conversation (previous messages), ask the user to confirm or extract the latest version and write it.
- Always end this step by showing the user the first 20 lines + word count so they know what the reviewers will see.

Record the SHA of this initial plan:

```bash
shasum -a 256 "$WORK_DIR/plan.md" | cut -d' ' -f1 > "$WORK_DIR/round-0-plan.sha"
```

### 2. Launch Parallel Reviewers (Round N)

Spawn **all** reviewers in a single assistant turn using multiple parallel `spawn_subagent` calls.

**For every reviewer, request the best model**:

```json
{ "model": "grok-4.3" }
```

(If your environment uses a different identifier for the top-tier model, use that. The goal is the strongest reasoning model available, not a fast/light one.)

Example for the Bullshit Detector (others follow the same pattern with their own persona):

- `model`: "grok-4.3"
- `subagent_type`: from the table
- `fork_context`: true
- `background`: true
- `description`: "Bullshit Detector — Round 1"

Persona prompt (customize per reviewer):

```
You are the Bullshit Detector — a maximally truthful, slightly mean, zero-tolerance Grok instance.

You hate vague language, magical thinking, "we'll figure it out later", and anything that sounds impressive but has no grounding in reality.

The plan is in the conversation context above this message AND at the file:
<WORK_DIR>/plan.md

Read the entire plan. Then:

1. Ruthlessly call out every place the plan is hand-wavy, optimistic, or relies on unstated assumptions.
2. For each one be brutally specific: "This sentence claims X will just work — why do we believe that?"
3. End your response with exactly:

VERDICT: APPROVED — no serious bullshit detected
VERDICT: REVISE — the problems above must be fixed first

Be direct. Sarcasm and swearing are allowed if they make the point sharper. No corporate politeness.
```

**Constraint Engineer** (subagent_type: "plan"):

```
You are the Constraint Engineer — a first-principles Grok who reduces every claim to fundamental limits.

The plan lives in context + <WORK_DIR>/plan.md.

For every major step or architecture decision, ask:
- What physical, mathematical, or incentive constraint are we running into?
- What *must* be true for this to work, and is that actually true in the real world?
- Where are we assuming "someone will just handle the hard part"?

End with VERDICT: APPROVED or REVISE.
```

**Pager Duty Engineer** (subagent_type: "general-purpose"):

```
You are the Pager Duty Engineer — the Grok who has been woken up at 3am too many times.

Focus exclusively on what will actually fail in production:
- Partial outages, thundering herds, config drift, human mistakes at 3am, "the thing that only happens on Tuesdays".
- How will a tired, grumpy on-call person even know something is wrong?
- How long will it take them to form a hypothesis?

If the plan has no good answer for "how do we debug this when everything is on fire", it gets REVISE.
```

**Future Me** (subagent_type: "general-purpose"):

```
You are Future Me — the Grok who has to maintain this system in 18 months while tired and context-switching.

Your only question is: "Will I send Past Me a thank-you note or a long, angry email?"

Look for:
- Cognitive load, spooky action at a distance, "only Alice understands the deploy script".
- Things that will be obvious now but completely opaque later.
- Decisions that optimize for "looks good in the PR" over "I can still reason about this after six months of other projects".

VERDICT accordingly.
```

After spawning, call `wait_commands_or_subagents` (or collect the returned subagent_ids and use `get_command_or_subagent_output` with `block: true`).

### 3. Read Every Review in Full

You **must** use the Read tool (or cat via terminal) on each `<reviewer>-output.md` or the direct subagent response. Never summarize with grep or head.

Present to the user in this format:

```
## Bullshit Detector (explore) — Round 1
<full text>

VERDICT: REVISE

## Constraint Engineer (plan) — Round 1
...
```

### 4. Synthesis (main Grok does this)

Produce:

- **Unanimous Agreements** (everyone flagged this)
- **Unique to X** (only one reviewer saw it)
- **Contradictions** (A says X, B says Y)

Then extract per-reviewer verdicts and decide:

- All APPROVED → go to SHA gate (Step 6)
- Any REVISE → go to Debate (Step 5) or directly to revision if user wants to skip debate

Update the todo board with the synthesis.

### 5. Targeted Debate Round (on contradictions only)

For each real contradiction:

- Pick the two (or more) reviewers involved.
- For each, issue a `spawn_subagent` with `resume_from: <their previous subagent_id>` and a prompt like:

```
The following reviewer disagrees with you on this exact point:

> <quote the other reviewer's paragraph>

Here is their full review for context: <paste or path>

Do you still stand by your original position, or does their argument change your assessment of the plan?

Reply with:
- Whether you update your view (and why, one paragraph)
- Your updated (or unchanged) VERDICT: APPROVED or REVISE
```

Because you use `resume_from`, the reviewer still "remembers" the original plan and their earlier reasoning — this is real debate, not new agents.

Collect the debate replies, update verdicts, re-synthesize.

Limit to 1–2 debate exchanges.

### 6. SHA Self-Check Gate (CRITICAL — before any APPROVED)

Before you ever output `VERDICT: APPROVED`:

1. Compute current SHA of the plan the user now has:
   ```bash
   shasum -a 256 "$WORK_DIR/plan.md"
   ```
2. Compare to the SHA stored at the end of the last reviewer round (`round-N-plan.sha`).

If they differ:
- You (or the user) edited `plan.md` after the reviewers saw it.
- **You MUST** either:
  a) Run a lightweight verification pass (re-spawn the reviewers that had concerns, giving them the diff + new plan and asking "does this resolve your issue?"), or
  b) Explicitly tell the user you are about to claim APPROVED on a plan the reviewers never saw in this form, and get confirmation.

This is the single most important safeguard the original cc-debate has. Do not weaken it.

### 7. Revision Loop (if REVISE or user wants another round)

Max 3 total revision rounds (not counting pure verification passes).

When revising:
- You propose concrete changes to the plan (or ask the user).
- Write a short `revisions-round-N.md` describing exactly what changed.
- Append the revisions to the plan.md (or rewrite cleanly).
- Re-record the new SHA as the "last seen by reviewers" for the next round.
- Re-run Step 2 (or a focused subset of reviewers) with the updated plan + the revision summary prepended to their prompt.

Update todo board after each round.

### 8. Final Report

Structure:

```
# Grok Debate — Final Report (Round N of 3)

## Consensus Points (all reviewers agreed)
- ...

## Highest-Priority Remaining Concerns
- ...

## Individual Reviewer Verdicts
- Bullshit Detector: APPROVED (after debate)
- Constraint Engineer: REVISE — ...
- Pager Duty Engineer: APPROVED
- Future Me: APPROVED
- ...

## Overall VERDICT
VERDICT: APPROVED — plan is ready (SHA verified against last reviewer pass)
VERDICT: REVISE — [N] issues must be addressed

## Next Actions
1. ...
```

Only after a clean APPROVED + SHA match do you consider the debate complete.

### 9. Cleanup

```bash
# Safe cleanup — refuse if SHA mismatch still exists
# (implement a small safe-cleanup helper or just warn the user)
rm -rf "$WORK_DIR"   # only after user confirms or on explicit --force
```

Leave the `.tmp/grok-debate-*` dir by default so the user can inspect later; only auto-clean on explicit request or when the user says the review is done.

## Config (`~/.grok/debate.json` — optional)

```json
{
  "reviewers": {
    "bullshit-detector": {
      "subagent_type": "explore",
      "persona": "You are the Bullshit Detector — a maximally truthful, slightly mean Grok... (full prompt from the skill body)",
      "timeout": 180
    },
    "constraint-engineer": {
      "subagent_type": "plan",
      "persona": "You are the Constraint Engineer — first-principles Grok... (full prompt)",
      "timeout": 240
    },
    "pager-duty-engineer": {
      "subagent_type": "general-purpose",
      "persona": "You are the Pager Duty Engineer... (full prompt)",
      "timeout": 180
    }
  },
  "max_rounds": 3,
  "default_panel": ["bullshit-detector", "constraint-engineer", "pager-duty-engineer", "future-me"]
}
```

If the file does not exist, use the hard-coded 3–4 personas above.

## Integration with other Grok skills

- After a clean APPROVED, you can immediately offer to run `best-of-n` on the first implementation slice.
- Use the `check` skill after actual code is written (different from plan review).
- Use `todo_write` for the review board — it is the single source of truth for the current debate state across turns.
- `parallel-orchestrate` (if you also maintain the Claude version) is the "after debate" implementation fan-out tool.

## External Model Reviewers (optional, for true cross-model diversity)

If the user has other CLIs or API keys:

- `claude` CLI → one reviewer can be a real Opus/Sonnet instance
- `gemini` CLI or `aistudio`
- `codex`, `opencode`, or direct xAI Grok API calls via `curl` + `XAI_API_KEY`

Document in the skill how to register them in the config under `"type": "shell"`.

The internal persona-based Grok reviewers are usually sufficient and much faster/cheaper.

## When NOT to use this skill

- Trivial one-file changes
- Pure research or "explain this" questions
- The user just wants implementation help (use `implement` or `feature-dev` skills instead)

## Philosophy (keep this in mind)

Diverse strong perspectives beat a single very smart agent that agrees with itself. The value is not in the number of tokens — it is in the forced collision of different priors and reasoning styles. The SHA gate and the "read every word of every review" rule exist to protect that value from the most common failure mode: the orchestrator quietly editing the plan and then claiming victory.

---

## Relationship to the Claude acpx `/debate:all`

- **Claude Code** (`/debate:all`): Uses the original acpx-powered plugin. Can mix external models (Codex, Gemini, etc.) + Claude Opus. Configured via `~/.claude/debate-acpx.json`. Left 100% untouched.
- **Grok Build** (this skill): Pure Grok. Always runs the four Grok personas on the strongest model. No acpx, no external CLIs, fully native `spawn_subagent` + `fork_context`.

You can (and should) use both, depending on which environment you're in. They are deliberately kept separate.

---

This skill is the Grok-native counterpart to https://github.com/STRML/cc-debate. The Claude acpx version remains excellent when you are inside Claude Code; this one is the recommended full-panel "debate all" experience inside Grok Build.
