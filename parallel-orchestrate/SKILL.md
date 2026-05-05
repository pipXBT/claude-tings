---
name: parallel-orchestrate
description: "Use when a design doc, implementation plan, spec, or feature breakdown needs to be implemented and parts of it can run independently. Reviews the document, identifies parallelizable work units, then fans out one Claude Opus agent per unit into its own cmux workspace tab (each in a separate git worktree), with the calling agent acting as orchestrator. Each fork inherits the orchestrator's recon as live conversation context. Triggers: 'implement this spec/plan/design in parallel', 'fan out this work', 'split this across agents', 'orchestrate opus agents in cmux', 'parallelize this build', or any time the user shares a design doc and asks Claude to execute it with multiple agents."
---

# parallel-orchestrate

Read a design or implementation document, decide what can run in parallel, then fan out one Opus agent per work unit into its own cmux workspace tab. Each agent inherits this session's recon as conversation history (via JSONL fork) and works in an isolated git worktree. The orchestrator (this session) monitors and reconciles.

This skill borrows two ideas from [STRML/cc-skills](https://github.com/STRML/cc-skills): JSONL-fork inheritance from `cc-fork`, and the recon-then-fanout-then-reconcile shape from `/code-cleanup`. The new piece is launching each fork as a visible cmux workspace tab running Opus, instead of capturing stdout from a headless `-p` invocation.

**Design choice — why forks inherit context.** There's a school of thought (e.g. obra/superpowers' `dispatching-parallel-agents`) that says forks should *never* inherit the parent session — that you construct exactly the context each agent needs, no more. That's the right call when forks are short, sub-tasks are small, and the parent context is full of irrelevant history. It's the wrong call here: with 5 Opus agents working a multi-file design doc, re-explaining the codebase + spec + decisions to each fork is wasteful (every fork pays parent-context tokens once, then prompt-cache covers spawns 2–N), and tends to produce subtly inconsistent interpretations across agents. Recon once, fan out many. The cost of inheritance is paid by prompt caching; the benefit — every fork starts with the same shared understanding — is what makes parallel implementation actually coherent.

## Preflight

Run all four. Abort with a clear message if any fail.

1. **cmux detected.** `[ -n "$CMUX_WORKSPACE_ID" ]`. If unset, the user is not inside cmux — abort and tell them to launch a cmux terminal first. The skill cannot run in plain Ghostty/iTerm/tmux.
2. **claude CLI on PATH.** `command -v claude`.
3. **git repo with a clean worktree.** `git rev-parse --is-inside-work-tree` and `git status --porcelain` empty (or warn the user about uncommitted changes — worktrees branch from current HEAD, so dirty changes won't be inherited).
4. **Not on main/master without consent.** `git rev-parse --abbrev-ref HEAD`. If the result is `main`, `master`, `trunk`, or `develop`, stop and confirm with the user explicitly before proceeding. Worktree mode branches *from* this branch; you don't want five Opus agents accidentally rooted on prod.
5. **Parent session JSONL exists.** `ls ~/.claude/projects/$(pwd | sed 's,[/.],-,g')/*.jsonl 2>/dev/null | head -1` — if empty, the current cwd has never had a Claude session, so there's nothing to fork from. Tell the user to start a session here first.

If any check fails, stop and report which one. Don't continue with degraded behaviour.

## Phase 1 — Recon (this session)

Read the document. Talk through it in this conversation — do not hoard understanding in a scratch file. Everything spoken in this turn becomes inherited context for every fork.

Cover, in this order:

1. **What is being built.** One paragraph in your own words. If you can't write it, you don't understand the doc yet — go re-read.
2. **Decompose into work items.** Number them. For each: a one-line description, the files/modules likely touched, and what "done" looks like.
3. **Dependency graph.** For each item, what other items must complete first. Items with no upstream deps are candidates for the first parallel wave.
4. **Shared substrate.** Anything every agent will need: shared types, DB migrations, generated code, new dependencies, a config file. This must land *before* the fanout, in pre-work — see Phase 3.
5. **Conflict surface.** Files or symbols that multiple items want to touch. These are why we use worktrees by default; flag them explicitly so reconcile knows where to look.
6. **Out of scope.** What the doc explicitly defers, or what should be a follow-up.

Read every file the doc references that you have not already opened. Run `tree -L 3 -I 'node_modules|dist|build|target|.venv|__pycache__'`. Get the project's typecheck/test/lint commands into the conversation.

State recon out loud. Concise prose, not bullet salad — but every fact a fork would need has to be on screen.

### Phase 1.5 — Critical review (don't skip)

Now read your own recon back, *adversarially*. Bad specs amplified across five Opus agents produce five times the wreckage, and the fanout makes mid-execution course-correction expensive. Surface explicitly:

- **Gaps.** What does the doc not specify that an agent will hit on turn 3? (Auth model? Error contract? Migration ordering? Empty-state behaviour?)
- **Contradictions.** Two paragraphs that imply different things. Two diagrams that disagree.
- **Unstated assumptions.** "X is already in place" claims you can't verify. "We'll use Y" without saying which version.
- **Decisions that should be the user's, not yours.** Anything where the doc punts ("TBD", "we'll decide later", "either approach works") and an agent will be forced to pick.
- **Verification gap.** How does each agent know it's done? Are there acceptance criteria, or just vibes?

If anything in this list is non-trivial: **stop and raise to the user before proceeding to Phase 2.** Don't guess. Don't fan out with a half-resolved spec — the cost of asking three clarifying questions now is much lower than the cost of merging five inconsistent agent outputs later. If everything's tight and the doc holds up, say so out loud and continue.

## Phase 2 — Plan

Group work items into agent tasks. Show the plan to the user and get explicit confirmation before spawning. Format:

```
Wave 1 (parallel, N agents):
  agent-01 [name: feat-payments]
    items: 3, 5, 7
    files: src/payments/**, tests/payments/**
    mandate: "Implement payment-flow per spec §3.2..."

  agent-02 [name: feat-notifications]
    items: 4, 8
    files: src/notify/**, tests/notify/**
    mandate: "Implement notification service per spec §3.3..."

  ...

Wave 2 (sequential, after Wave 1 reconciles):
  - Integration tests across payments + notifications
  - Update README and CHANGELOG

Pre-work (this session, before any fanout):
  - Generate shared OrderEvent type in src/types/events.ts
  - Add `decimal.js` to package.json
  - Run migration 20260101_add_payments_table.sql
```

Rules for grouping:

- **No two agents in the same wave touch the same file.** This is the main constraint. If two items want the same file, either merge them into one agent, or move one to a later wave.
- **Aim for 3–6 agents per wave.** Fewer than 3 isn't worth the orchestration overhead — just do them sequentially in this session. More than 6 makes reconcile painful and saturates Opus quota fast.
- **Each agent should be 30–90 minutes of work.** Smaller and the Opus startup tax dominates; larger and you lose the visibility benefit of one-tab-per-task.
- **Tests next to code.** The agent that writes a feature also writes its unit tests. Cross-feature integration tests go in a later wave.

Ask the user:

- Confirm the wave-1 split (offer to merge/split agents).
- Choose a mode (default: `worktree`):
  - **`worktree`** — each agent in its own `git worktree`, branched from current HEAD. Reconcile = merge. Safest; required for any fanout that edits the same files.
  - **`shared`** — all agents in the current working tree, relying on file-ownership boundaries. Faster reconcile (no merge), but one misbehaving agent corrupts the tree for everyone.
  - **`dry-run`** — agents propose patches as text reports; nothing is applied until reconcile reviews. Use for fragile codebases or first time on this skill.

Do not proceed without explicit confirmation ("yes", "go", "spawn", "do it"). If the user wants changes, edit the plan and re-confirm.

## Phase 3 — Pre-work (this session)

Land the shared-substrate items from recon §4 *before* fanning out. Run typecheck/tests after pre-work — green is the baseline every fork branches from.

Pre-work happens in *this* session because every fork inherits this session's JSONL. Things done here are visible to every agent without re-explanation. Things done after the fork point are not.

Examples of pre-work:
- Generate or update shared types
- Add a dependency to package.json / Cargo.toml / pyproject.toml and install
- Run a DB migration that all agents will read against
- Create empty directory scaffolding the agents will fill in
- Resolve any "we should do X before Y" the recon surfaced

Commit pre-work as a single tidy commit (`chore(orchestrate): pre-fanout substrate for <feature>`). Worktree mode branches from this commit.

## Phase 4 — Fanout

Run the spawn script. It handles JSONL fork, worktree creation, and cmux workspace launch.

```bash
python3 ${CLAUDE_SKILLS_DIR:-~/.claude/skills}/parallel-orchestrate/scripts/spawn-cmux.py \
  --mode worktree \
  --model opus \
  --session-tag <short-name-for-this-fanout> \
  --task "feat-payments:Implement payment flow per spec §3.2. Files in scope: src/payments/**, tests/payments/**. When done, write your report to .tmp/parallel-orchestrate/<session-tag>/reports/feat-payments.md and run 'cmux notify --title agent-done --body feat-payments'." \
  --task "feat-notifications:Implement notification service per spec §3.3. Files in scope: src/notify/**, tests/notify/**. When done, write report to .tmp/parallel-orchestrate/<session-tag>/reports/feat-notifications.md and notify." \
  --task "...":...
```

What the script does, per task:

1. Generates a UUID for the fork.
2. Creates `<repo>/../<repo>-worktrees/<session-tag>/<task-name>` as a worktree on a fresh branch `parallel/<session-tag>/<task-name>`. Skipped if `--mode shared` or `--mode dry-run`.
3. Copies the parent JSONL into the worktree's encoded project dir (`~/.claude/projects/<encoded-worktree-path>/<uuid>.jsonl`). This is what makes `claude --resume` resolve under the new cwd. Without this step the fork can't find the parent session.
4. Calls `cmux new-workspace --command "cd <worktree> && claude --resume <uuid> --model opus '<full task prompt>'"`. Each spawn becomes its own vertical sidebar tab.
5. Renames the workspace to `<session-tag>:<task-name>` so the user can tell tabs apart.
6. Writes a manifest at `.tmp/parallel-orchestrate/<session-tag>/manifest.json` listing every fork's UUID, worktree, branch, and cmux workspace ref. Reconcile reads this.

Read `references/spawn-script-internals.md` only if you need to debug or extend the script — the SKILL.md instructions above are sufficient for normal use.

The full task prompt (the part after `--model opus`) should follow this structure. Every fork sees the recon + critical review + plan + pre-work as inherited conversation, so the prompt itself stays tight:

```
Mandate: <one sentence — what this agent owns>
Scope: <files/modules in bounds, e.g. "src/payments/**, tests/payments/**">
Out of scope: <what NOT to touch, e.g. "src/notify/** is owned by another agent">
Done when:
  - <acceptance criterion 1, e.g. "all unit tests for payments pass">
  - <acceptance criterion 2, e.g. "no new TypeScript errors in scope">
  - <acceptance criterion 3, e.g. "report written">

Stop and report partial — DO NOT GUESS — if any of:
  - You hit a missing dependency, undocumented API, or unclear instruction.
  - A verification (typecheck/test) fails three times despite different fixes.
  - You discover the spec contradicts itself or contradicts existing code.
  - You'd need to touch a file outside your scope to finish.

When done (or when blocked):
  1. Write a structured report to .tmp/parallel-orchestrate/<session-tag>/reports/<task-name>.md.
     Sections: Mandate · What I did · What I skipped + why · Files touched · Tests run + result · Open questions for orchestrator · Follow-ups.
  2. Run: cmux notify --title agent-done --body <task-name>
```

Why the stop-and-ask criteria matter: a fork that guesses on a missing dep will produce code that compiles but breaks integration; a fork that papers over a failed test by relaxing the assertion produces a green build that's lying. Cheap to fix at fork time, expensive to find at reconcile. Borrowed shape from `obra/superpowers/executing-plans` ("stop when blocked, don't guess"), tightened for the parallel case where guessing compounds.

## Phase 5 — Monitor

Stay in the orchestrator tab. Update progress so the sidebar shows wave state:

```bash
cmux set-progress 0.0 --label "Wave 1 spawned, 0/N done"
cmux set-status orchestrate "Wave 1 in flight" --icon hammer --color "#1565C0"
```

Two ways to detect agent completion:

1. **Push (preferred).** Each agent runs `cmux notify --title agent-done --body <task-name>` at the end of its mandate. The orchestrator polls `.tmp/parallel-orchestrate/<session-tag>/reports/` for new files and updates progress as each shows up.
2. **Pull.** Periodically `cmux read-screen --surface <ref> --lines 30` for each fork's surface (refs in the manifest) and look for the agent's "DONE" signal.

Update `set-progress` as each report lands. When all N reports exist:

```bash
cmux set-progress 1.0 --label "Wave 1 complete, reconciling"
cmux notify --title "Wave 1 done" --body "$N agents finished, reconciling"
```

Don't read agent surfaces obsessively — give them room. Five-minute poll is fine. If an agent's surface goes silent (no progress for 15+ minutes), `cmux read-screen` it once and surface what you see to the user; don't auto-intervene.

## Phase 6 — Reconcile

In the orchestrator session:

1. **Read every report in full.** `.tmp/parallel-orchestrate/<session-tag>/reports/*.md`. No grep-skim. Each report should declare: what was implemented, what was skipped and why, files touched, test status, follow-ups.
2. **Surface findings inline for the user.** One paragraph per agent.
3. **Worktree mode: merge.** For each agent's branch, in order: `git merge --no-ff parallel/<session-tag>/<task-name>`. Resolve conflicts. After each merge, run typecheck + tests; revert that merge if red and ask the user what to do.
4. **Shared mode: just run typecheck + tests.** All agents already wrote to the same tree.
5. **Dry-run mode: review patches with the user.** Apply the ones they approve, skip the rest.
6. **Commit per agent** with their mandate as the message body: `feat(payments): <one-line>` then a paragraph from the report.
7. **Compile follow-ups.** Anything every agent flagged as "should do later" gets a single follow-up issue or a TODO list at the top of the next-wave plan.

## Phase 7 — Cleanup

```bash
python3 ${CLAUDE_SKILLS_DIR:-~/.claude/skills}/parallel-orchestrate/scripts/spawn-cmux.py \
  --cleanup --session-tag <session-tag>
```

This removes the forked JSONL files (kept in each worktree's project dir), closes the agent workspaces in cmux, and optionally removes the worktrees (`--remove-worktrees`). Keep worktrees if you want to inspect anything; they're cheap.

The orchestrator tab keeps its `set-status orchestrate "Wave 1 reconciled"` until you `clear-status orchestrate`.

## Common mistakes

| ❌ Wrong | ✅ Right |
|---------|---------|
| Skip critical review, fan out the moment you've decomposed | Read recon adversarially — gaps and contradictions raised to user *before* fanout |
| Two agents own overlapping files, "they'll figure it out" | Either merge them into one agent or move one to wave 2; never overlap files in the same wave |
| Vague mandate: "improve the payments code" | Specific mandate: "implement §3.2 payment flow in src/payments/**, tests passing, report at <path>" |
| Bundle two concerns: "implement X and also clean up Y" | One mandate per agent. Forks are cheap; spawn another for Y |
| Tell every fork the full project background in its prompt | Recon happens once in the orchestrator session; forks inherit it via JSONL fork — keep prompts tight |
| Land shared types/migrations *during* fanout | Land them as pre-work in the orchestrator, commit, then fan out from that commit |
| Fan out 2 items because "it might save time" | 2 isn't worth the ceremony — do them sequentially. 3+ before fanout |
| Skim agent reports at reconcile | Read every report in full — reconcile is where the orchestrator earns its keep |
| Merge an agent's branch and skip the test run | Run typecheck + tests after every merge; revert that merge if red |
| Let an agent guess past a missing dep or unclear spec | Each agent's mandate includes explicit stop-and-report-partial criteria |
| Spawn 8 Opus agents simultaneously | Start with 3-agent waves before going to 6; Opus quota burns fast at 8× |
| Fan out tasks that need each other's output | That's a sequential chain, not a parallel wave — put the dependent one in wave 2 |
| Skim recon and start spawning fast | Recon depth determines fork quality. Two-paragraph recon → forks ask basic questions on turn 1. Thorough recon → forks start writing code |

## When NOT to use this skill

- Single linear task → just do it in this session.
- Task fits in one file → no parallelism gain.
- User isn't in cmux → the visibility benefit goes away; use the Task tool or `cc-fork` directly.
- Codebase has heavy dynamic wiring (Rails autoload, Django signals, WordPress hooks) → cross-cutting changes need single-author awareness; a fanout will produce subtly broken code.
- The doc itself is half-baked — fanout amplifies bad specs. Tighten the spec first.

## Credits

JSONL-fork-inherits-context is the trick from [`cc-fork`](https://github.com/STRML/cc-skills/blob/main/bin/cc-fork). The recon-then-fanout-then-reconcile shape is from [`/code-cleanup`](https://github.com/STRML/cc-skills/blob/main/commands/code-cleanup.md). cmux is from [manaflow-ai/cmux](https://github.com/manaflow-ai/cmux). The critical-review-before-execute step and the stop-and-report-partial guidance for agents are adapted from [`obra/superpowers/executing-plans`](https://github.com/obra/superpowers/blob/main/skills/executing-plans/SKILL.md); the common-mistakes table format is adapted from [`obra/superpowers/dispatching-parallel-agents`](https://github.com/obra/superpowers/blob/main/skills/dispatching-parallel-agents/SKILL.md). This skill stitches them together.
