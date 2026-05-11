---
name: parallel-orchestrate
description: "Use when a design document, implementation plan, or feature spec contains multiple independent work units that can be implemented simultaneously by different agents — and the orchestrator session is running inside a cmux terminal. Invoke as `parallel-orchestrate` (no namespace prefix)."
---

# parallel-orchestrate

Decompose a design document into independent work units, run one agent per unit in its own cmux workspace tab and git worktree, then reconcile the parallel output in the orchestrator session. Each agent is assigned the model that matches its task complexity — Opus for open-ended reasoning, Sonnet for well-specified mechanical work, Haiku for pure analysis or read-only tasks.

## When to use

- Design doc with 3+ work items that don't share files
- Long task that would otherwise occupy one session for an hour or more
- Currently inside a cmux terminal session

## When NOT to use

- Single linear task or task that fits in one file
- Not running inside cmux (the visibility-as-tabs benefit goes away)
- Codebase has heavy dynamic wiring (Rails autoload, Django signals, WordPress hooks)
- Spec is half-baked — fanout amplifies bad specs

## Preflight

Abort with a clear message if any check fails. Do not continue with degraded behaviour.

1. **cmux detected** — `[ -n "$CMUX_WORKSPACE_ID" ]`
2. **claude CLI on PATH** — `command -v claude`
3. **Git repo with a prepared HEAD** — Run `git status --porcelain`. Handle both types of dirty state before fanout:
   - **Modified tracked files** (`M` prefix): stash with `git stash push -m "WIP before parallel fanout"` or commit. Worktrees branch from HEAD, so these changes are invisible to agents until you do this.
   - **Untracked new source files** (`??` prefix): `git stash` does NOT capture these. Either use `git stash -u` (stash including untracked) or `git add <files> && git commit` as a pre-fanout substrate commit. Any file an agent imports or depends on must be in HEAD before fanout.
   - Untracked non-source files (build artifacts, logs, CSVs) can stay — worktrees don't inherit them and agents rarely need them.
4. **Not on `main`/`master`/`trunk`/`develop` without consent** — confirm explicitly before branching from a protected branch
5. **Parent session JSONL exists** — `ls ~/.claude/projects/<encoded-cwd>/*.jsonl` returns at least one substantive file

## Phase 1 — Recon

Read the document. State recon out loud in this conversation — every sentence becomes inherited context for every fork via JSONL fork. Cover, in this order:

1. **What is being built** — one paragraph in your own words
2. **Work items** — numbered, each with files touched and what "done" looks like
3. **Dependency graph** — what blocks what; items with no upstream deps are wave-1 candidates
4. **Shared substrate** — types, migrations, dependencies every agent will need (becomes pre-work)
5. **Conflict surface** — files multiple items want
6. **Out of scope** — what the doc explicitly defers

Run `tree -L 3 -I 'node_modules|dist|build|target|.venv|__pycache__'`. Capture the project's typecheck/test/lint commands into the conversation.

## Phase 1.5 — Critical review

Read your own recon adversarially. Surface explicitly:

- **Gaps** — what the doc doesn't specify that an agent will hit on turn 3
- **Contradictions** — paragraphs or diagrams that disagree
- **Unstated assumptions** — "X is already in place" claims you can't verify
- **Decisions that are the user's, not yours** — TBDs the doc punts on
- **Verification gaps** — how does each agent know it's done?

If anything non-trivial: stop and raise to the user before fanout. Bad specs amplified across five agents produce five times the wreckage, and mid-fanout course-correction is expensive.

## Phase 2 — Plan

Group work items into agent tasks. For each task, score its complexity and assign a model before showing the plan.

### Complexity scoring

Score each task across four dimensions. Total score determines the model.

| Dimension | 1 pt — Mechanical | 2 pts — Moderate | 3 pts — Complex |
|-----------|-------------------|------------------|-----------------|
| **Instruction clarity** | Exact steps given (line numbers, code snippets) | Steps outlined, some judgment needed | Open-ended; agent must decide approach |
| **Reasoning depth** | Pure search-replace / delete / rename | Needs to understand context to proceed | Tradeoffs to weigh; no single right answer |
| **Spec completeness** | Every edge case covered | Gaps exist but are inferable | Significant gaps; agent must design |
| **Verification** | Pass/fail (tests green, lint clean) | Multi-step checks with judgment calls | Hard to verify; relies on agent's own assessment |

**Score → Model:**
- **4–5 pts → Haiku** — read-only analysis, pure reporting, trivial deletes with zero judgment needed
- **6–8 pts → Sonnet** — well-specified implementation, mechanical refactors, tasks where "done" is unambiguous
- **9–12 pts → Opus** — architectural decisions, open-ended analysis, tasks with spec gaps the agent must fill, anything where a wrong call is hard to reverse

When in doubt between two tiers, score the **uncertainty** rather than the task surface area — a large-but-mechanical task is still Sonnet.

Show the plan and get explicit confirmation before spawning. Format:

```
Wave 1 (parallel, N agents):
  agent-01 [name: feat-payments, model: sonnet, score: 7]
    items: 3, 5, 7
    files: src/payments/**, tests/payments/**
    score: clarity=2, reasoning=2, spec=2, verify=1 → 7 → sonnet
    mandate: "Implement payment-flow per spec §3.2..."

  agent-02 [name: feat-notifications, model: opus, score: 10]
    items: 4, 8
    files: src/notify/**, tests/notify/**
    score: clarity=3, reasoning=3, spec=2, verify=2 → 10 → opus
    mandate: "..."

Wave 2 (sequential, after Wave 1 reconciles):
  - Integration tests across payments + notifications

Pre-work (this session, before any fanout):
  - Generate shared OrderEvent type in src/types/events.ts
  - Add `decimal.js` to package.json
```

Rules for grouping:

- **No two agents in the same wave touch the same file** — the central constraint
- **3–6 agents per wave** — fewer isn't worth orchestration overhead, more saturates Opus quota and makes reconcile painful
- **30–90 minutes of work per agent** — smaller and Opus startup tax dominates; larger and one-tab-per-task visibility breaks
- **Tests next to code** — agent that writes a feature also writes its unit tests; cross-feature integration tests go in a later wave

Choose mode (default: `worktree`):

- **`worktree`** — each agent in its own `git worktree`, branched from current HEAD. Reconcile = merge. Required for any fanout that edits the same files.
- **`shared`** — all agents in the current tree, file-ownership boundaries. Faster reconcile, but one misbehaving agent corrupts the tree.
- **`dry-run`** — agents propose patches as text reports; nothing applied until reconcile reviews.

Wait for explicit confirmation ("yes", "go", "spawn") before continuing. If the user wants changes, edit the plan and re-confirm.

## Phase 3 — Pre-work

Land shared-substrate items from recon §4 in this session before fanning out. Run typecheck/tests after — green is the baseline every fork branches from. Commit as a single tidy commit: `chore(orchestrate): pre-fanout substrate for <feature>`.

Pre-work happens here because every fork inherits this session's JSONL. Things done here are visible to every agent without re-explanation. Things done after the fork point are not.

## Phase 4 — Fanout

Run the spawn script. Always pass `--parent` with your current session UUID — active repos with many prior sessions have larger historical JSONLs and the default largest-file heuristic will pick the wrong one.

Find your current session UUID: `ls -lt ~/.claude/projects/<encoded-cwd>/*.jsonl | head -1`

**Single model (all agents same tier):**
```bash
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-cmux.py \
  --mode worktree \
  --model sonnet \
  --session-tag <session-tag> \
  --parent <current-session-uuid> \
  --stagger 3 \
  --task "feat-payments:Implement payment flow per spec §3.2..." \
  --task "feat-notifications:..."
```

**Mixed models (agents on different tiers):** `--model` is global to one script invocation, so use two calls — one per model tier. Order doesn't matter; all worktrees branch from the same HEAD:
```bash
# Opus agents
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-cmux.py \
  --mode worktree --model opus --session-tag <tag> --parent <uuid> --stagger 3 \
  --task "feat-arch:..."

# Sonnet agents (separate invocation, same session-tag)
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-cmux.py \
  --mode worktree --model sonnet --session-tag <tag> --parent <uuid> --stagger 3 \
  --task "feat-payments:..." \
  --task "feat-notifications:..."
```

**Path note:** if your repo path contains underscores (e.g. `my_project`), the script may compute the wrong project directory. Verify: `ls ~/.claude/projects/ | grep <repo-name>`. If the real dir uses dashes where you see underscores, either pass `--parent <uuid>` (which bypasses the directory lookup entirely) or create a symlink: `ln -s ~/.claude/projects/<dash-version> ~/.claude/projects/<underscore-version>`.

Per task, the script:

1. Generates a UUID for the fork
2. Creates a worktree at `<repo>/../<repo>-worktrees/<session-tag>/<task-name>` on a fresh branch `parallel/<session-tag>/<task-name>` (skipped if `--mode shared` or `--mode dry-run`)
3. Copies the parent JSONL into the worktree's encoded project dir, so `claude --resume <uuid>` resolves
4. Launches the fork as a cmux workspace tab
5. Renames the workspace to `<session-tag>:<task-name>`
6. Writes a manifest at `.tmp/parallel-orchestrate/<session-tag>/manifest.json`

Each task prompt should follow this structure (forks inherit recon as conversation context, so prompts stay tight):

```
Mandate: <one sentence — what this agent owns>
Scope: <files in bounds, e.g. "src/payments/**, tests/payments/**">
Out of scope: <files NOT to touch, e.g. "src/notify/** is owned by another agent">
Done when:
  - <criterion 1, e.g. "all unit tests for payments pass">
  - <criterion 2, e.g. "no new TypeScript errors in scope">
  - <criterion 3, e.g. "report written">

Stop and report partial — DO NOT GUESS — if any of:
  - Missing dependency, undocumented API, or unclear instruction
  - Verification fails three times despite different fixes
  - Spec contradicts itself or contradicts existing code
  - Need to touch a file outside scope to finish

When done (or blocked):
  1. Write report to .tmp/parallel-orchestrate/<session-tag>/reports/<task-name>.md
     Sections: Mandate · What I did · What I skipped + why · Files touched · Tests run + result · Open questions · Follow-ups
  2. Run: cmux notify --title agent-done --body <task-name>
```

## Phase 5 — Monitor

Stay in the orchestrator tab. Update progress so the sidebar reflects wave state:

```bash
cmux set-status orchestrate "Wave 1 in flight" --icon hammer --color "#1565C0"
cmux set-progress 0.0 --label "0/N done"
```

Watch `.tmp/parallel-orchestrate/<session-tag>/reports/` for new files. Update `set-progress` as each lands. Don't read agent surfaces obsessively — five-minute poll is fine. If a surface goes silent for 15+ minutes, `cmux read-screen --surface <ref> --lines 30` once and surface to user; don't auto-intervene.

When all N reports exist:

```bash
cmux set-progress 1.0 --label "Wave 1 complete, reconciling"
cmux notify --title "Wave 1 done" --body "$N agents finished"
```

## Phase 6 — Reconcile

1. **Read every report in full.** No skim. Each report should declare: what was implemented, what was skipped + why, files touched, test status, follow-ups.
2. **Surface findings inline for the user** — one paragraph per agent.
3. **Worktree mode:** `git merge --no-ff parallel/<session-tag>/<task-name>` per agent in dependency order. Resolve conflicts. After each merge, run typecheck + tests. Revert that merge and ask the user if red.
4. **Shared mode:** run typecheck + tests. All agents already wrote to the same tree.
5. **Dry-run mode:** review patches with the user. Apply approved, skip rest.
6. **Commit per agent** with mandate as message: `feat(payments): <one-line>` plus a paragraph from the report.
7. **Compile follow-ups** from every report into one TODO list for the next wave or a follow-up issue.

## Phase 7 — Cleanup

```bash
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-cmux.py \
  --cleanup --session-tag <session-tag>
```

Removes forked JSONL files, closes agent workspaces in cmux, optionally removes worktrees with `--remove-worktrees`. Keep worktrees if you might want to inspect; they're cheap.

Clear the orchestrator status when fully done: `cmux clear-status orchestrate`.

## Common mistakes

| ❌ Wrong | ✅ Right |
|---------|---------|
| Skip critical review, fan out the moment you've decomposed | Read recon adversarially before fanout — gaps and contradictions raised to user first |
| Two agents own overlapping files, "they'll figure it out" | Merge them into one agent or move one to wave 2; never overlap files in the same wave |
| Vague mandate: "improve the payments code" | Specific: "implement §3.2 in src/payments/**, tests passing, report at <path>" |
| Bundle two concerns: "implement X and clean up Y" | One mandate per agent. Forks are cheap; spawn another for Y |
| Tell every fork the full project background in its prompt | Recon happens once in the orchestrator; forks inherit via JSONL — keep prompts tight |
| Land shared types/migrations *during* fanout | Land them as pre-work, commit, then fan out from that commit |
| Fan out 2 items because "it might save time" | 2 isn't worth ceremony — sequential is fine. 3+ before fanout |
| Skim agent reports at reconcile | Read every report in full — reconcile is where the orchestrator earns its keep |
| Merge an agent's branch and skip the test run | Run typecheck + tests after every merge; revert if red |
| Let an agent guess past a missing dep or unclear spec | Each mandate includes explicit stop-and-report-partial criteria |
| Spawn 8 Opus agents simultaneously | Start with 3-agent waves before going to 6; Opus quota burns fast at 8× |
| Skim recon and start spawning fast | Recon depth determines fork quality. Two-paragraph recon → forks ask basic questions on turn 1. Thorough recon → forks start writing code |
| Assign Opus to every agent by default | Score each task first. Mechanical tasks with explicit instructions are Sonnet. Pure read/report tasks are Haiku. Reserve Opus for tasks with real reasoning demand or spec gaps. |
| Stash before fanout without checking `??` lines | `git stash` skips untracked files. New source files won't appear in worktrees. Use `git stash -u` or commit them as a substrate commit first. |
| Omit `--parent` when spawning | Active repos have many large historical JSONLs. Without `--parent`, the script picks the largest file — usually a past session, not the live one. Forks inherit the wrong context. |
