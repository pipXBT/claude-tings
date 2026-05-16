---
name: parallel-orchestrate
description: "Use when a design document, implementation plan, or feature spec contains multiple independent features that can be implemented simultaneously by different agents. Spawns one agent per feature in its own git worktree on a feature/<name> branch, with a file-mailbox so agents can DM each other and the orchestrator. Terminal-agnostic (iTerm2, Terminal.app, tmux, plain SSH — no multiplexer required). Invoke as `parallel-orchestrate`."
---

# parallel-orchestrate

Decompose a design document into one **feature per agent**, then for each feature spawn:

- a git worktree on a fresh `feature/<name>` branch (CodeRabbit-friendly; other PR-review skills work unchanged)
- a JSONL-forked `claude --resume <uuid> -p` subprocess that inherits the orchestrator's recon as live conversation context
- a file mailbox so agents can DM each other and the orchestrator while running

The **current session is the orchestrator** — it does recon, fans out, brokers cross-agent messages, then reconciles. No new terminal tabs, no multiplexer dependency: agents run as background processes in the orchestrator's environment, output goes to log files.

**REQUIRED SUB-SKILL:** Invoke `karpathy-guidelines` before Phase 1 and keep it active for the whole run. Each spawned agent's prompt also begins by invoking `karpathy-guidelines` — discipline propagates to every fork (see Phase 4).

## When to use

- Design doc with 3+ features that don't share files
- Each feature wants its own PR / branch for CodeRabbit, ultrareview, or other branch-scoped review
- Long task that would otherwise occupy one session for an hour or more

## When NOT to use

- Single linear task or task that fits in one file
- Codebase has heavy dynamic wiring (Rails autoload, Django signals, WordPress hooks) — single-author awareness needed
- Spec is half-baked — fanout amplifies bad specs
- You want the agents to literally see each other's terminal output (use a multiplexer + separate sessions for that; this skill assumes async file-based coordination)

## Preflight

Abort with a clear message if any check fails. Do not continue with degraded behaviour.

1. **`claude` CLI on PATH** — `command -v claude`
2. **Inside a git repo with a prepared HEAD** — Run `git status --porcelain`. Handle both types of dirty state before fanout:
   - **Modified tracked files** (`M`): stash with `git stash push -m "WIP before parallel fanout"` or commit. Worktrees branch from HEAD, so these changes are invisible to agents until you do this.
   - **Untracked new source files** (`??`): `git stash` does NOT capture these. Either use `git stash -u` (stash including untracked) or `git add <files> && git commit` as a pre-fanout substrate commit. Any file an agent imports must be in HEAD before fanout.
   - Untracked non-source files (build artifacts, logs, CSVs) can stay.
3. **Not on `main`/`master`/`trunk`/`develop` without consent** — confirm explicitly before branching from a protected branch.
4. **Parent session JSONL exists** — `ls ~/.claude/projects/<encoded-cwd>/*.jsonl` returns at least one substantive file. You will pass this session's UUID as `--parent`.
5. **No conflicting feature branches** — for each planned task name, verify `git rev-parse --verify --quiet refs/heads/feature/<name>` returns non-zero. If a branch already exists, rename the task or delete the branch first.

## Phase 1 — Recon

Read the document. State recon out loud in this conversation — every sentence becomes inherited context for every fork via JSONL fork. Cover, in this order:

1. **What is being built** — one paragraph in your own words
2. **Features** — numbered, each with files touched and what "done" looks like (one feature = one agent = one branch)
3. **Dependency graph** — what blocks what; features with no upstream deps are wave-1 candidates
4. **Shared substrate** — types, migrations, dependencies every agent will need (becomes pre-work)
5. **Inter-feature contracts** — APIs / events / shared types where agents will need to coordinate via mailbox
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

One feature per agent. For each, score complexity and assign a model before showing the plan.

### Complexity scoring

| Dimension | 1 pt — Mechanical | 2 pts — Moderate | 3 pts — Complex |
|-----------|-------------------|------------------|-----------------|
| **Instruction clarity** | Exact steps given (line numbers, code snippets) | Steps outlined, some judgment needed | Open-ended; agent must decide approach |
| **Reasoning depth** | Pure search-replace / delete / rename | Needs to understand context to proceed | Tradeoffs to weigh; no single right answer |
| **Spec completeness** | Every edge case covered | Gaps exist but are inferable | Significant gaps; agent must design |
| **Verification** | Pass/fail (tests green, lint clean) | Multi-step checks with judgment calls | Hard to verify; relies on agent's own assessment |

**Score → Model:**
- **4–5 pts → Haiku** — read-only analysis, pure reporting, trivial deletes with zero judgment needed
- **6–8 pts → Sonnet** — well-specified implementation, mechanical refactors, tasks where "done" is unambiguous
- **9–12 pts → Opus** — architectural decisions, open-ended analysis, tasks with spec gaps the agent must fill

When in doubt between two tiers, score the **uncertainty** rather than the task surface area.

Show the plan and get explicit confirmation before spawning. Format:

```
Wave 1 (parallel, N agents on feature branches):
  agent feature/payments [model: sonnet, score: 7]
    scope: src/payments/**, tests/payments/**
    score: clarity=2 reasoning=2 spec=2 verify=1 → 7 → sonnet
    mandate: "Implement payment flow per spec §3.2..."
    may message: feature/notifications (for OrderEvent contract)

  agent feature/notifications [model: opus, score: 10]
    scope: src/notify/**, tests/notify/**
    score: clarity=3 reasoning=3 spec=2 verify=2 → 10 → opus
    mandate: "..."
    may message: feature/payments

Wave 2 (sequential, after Wave 1 reconciles):
  - Integration tests across payments + notifications

Pre-work (this session, before any fanout):
  - Generate shared OrderEvent type in src/types/events.ts
  - Add `decimal.js` to package.json
```

Rules for grouping:

- **One feature per agent** — that's the whole point of branch-per-agent. If two work items truly share a single feature, they're one agent.
- **No two agents in the same wave touch the same file** — the central constraint; mailbox coordination is for *interface contracts*, not shared edits
- **3–6 agents per wave** — fewer isn't worth orchestration overhead, more saturates Opus quota and makes reconcile painful
- **30–90 minutes of work per agent**
- **Tests next to code** — agent that writes a feature also writes its unit tests; cross-feature integration tests go in a later wave

Mode (default: `worktree`):

- **`worktree`** — each agent in `git worktree add -b feature/<name>`, branched from HEAD. Reconcile = merge per branch. This is what makes CodeRabbit / ultrareview / per-feature PRs work.
- **`shared`** — no worktree, no branch. All agents in the orchestrator tree. Use only when you genuinely want one combined PR and trust the file-ownership boundaries.

Wait for explicit confirmation ("yes", "go", "spawn") before continuing.

## Phase 3 — Pre-work

Land shared-substrate items from recon §4 in this session before fanning out. Run typecheck/tests after — green is the baseline every fork branches from. Commit as a single tidy commit: `chore(orchestrate): pre-fanout substrate for <feature-set>`.

Pre-work happens here because every fork inherits this session's JSONL. Things done here are visible to every agent without re-explanation. Things done after the fork point are not.

## Phase 4 — Fanout

Find your current session UUID — this becomes `--parent`:

```bash
ls -lt ~/.claude/projects/$(pwd | sed 's|[^a-zA-Z0-9]|-|g')/*.jsonl | head -1
```

Run the spawn script. `--parent` is **required** — the orchestrator must explicitly designate which session is the fork parent (active repos have many large historical JSONLs; auto-picking the largest is wrong often enough to disallow).

**Single model:**
```bash
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag <tag> \
  --parent <orchestrator-session-uuid> \
  --model sonnet \
  --stagger 2 \
  --task "payments:Implement payment flow per spec §3.2..." \
  --task "notifications:..."
```

**Mixed models (per-task override):**
```bash
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag <tag> --parent <uuid> --stagger 2 \
  --task "payments:sonnet:Implement payment flow..." \
  --task "platform-arch:opus:Design event bus..." \
  --task "audit-report:haiku:Read all routes and produce a coverage matrix..."
```

Per task, the script:

1. Verifies branch `feature/<task-name>` doesn't already exist; aborts if it does
2. Creates worktree at `<repo>/../<repo>-worktrees/<task-name>` on branch `feature/<task-name>`
3. Generates a UUID; copies the parent JSONL into the worktree's encoded project dir so `claude --resume <uuid>` resolves
4. Sets up `mailbox/<task-name>/{inbox,seen,outbox}/`
5. Launches `claude --resume <uuid> --model <m> --dangerously-skip-permissions -p <wrapped-prompt>` as a background subprocess; PID, stdout, stderr captured in `logs/`
6. Writes manifest at `.tmp/parallel-orchestrate/<tag>/manifest.json`

The script wraps the user's mandate with: agent name, branch, worktree path, list of peer names, mailbox protocol, done-criteria, stop-and-report-partial criteria, and an explicit instruction to invoke `karpathy-guidelines` as the first action. **Keep mandate text tight** — the script handles the structural scaffold.

### Mailbox protocol (what every agent does)

Every agent has a mailbox at `.tmp/parallel-orchestrate/<tag>/mailbox/<agent-name>/`:

- `inbox/` — messages addressed to this agent; agent polls with `ls inbox/` after every major step
- `seen/` — agent moves processed messages here after reading
- `outbox/` — audit copy of messages this agent sent

To message a peer or the orchestrator, an agent writes a markdown file to `<mailbox-root>/<recipient>/inbox/<UTC-timestamp>-from-<sender>.md` and mirrors it into its own `outbox/`. The orchestrator has its own mailbox too (`mailbox/orchestrator/`) — agents address it as `orchestrator`.

Use messages for genuine cross-agent need: interface contracts, blocking questions, "I'm changing the OrderEvent shape, here's the new TypeScript type." Don't use for status chatter — that's what reports are for.

### CRITICAL: agents must NOT block on mailbox replies

When an agent sends a blocking-decision MSG to the orchestrator, it MUST exit, not wait. `claude -p` has no event loop — the only ways to "pause" are emit-tokens-continuously (expensive) or bash `sleep` loops (no tokens → Anthropic API stream's idle timeout fires after ~5–10 min → `API Error: Stream idle timeout - partial response received` → process dies, WIP often unsaved).

Observed failure (HyperShield Wave 2, 2026-05-16): PR-D agent sent a crypto-scheme sign-off MSG, polled mailbox in bash loop, died ~10 min later with the API stream timeout. WIP files survived in the worktree but no commits, no PR.

Protocol after sending a blocking MSG:

1. Write the MSG to `mailbox/orchestrator/inbox/<UTC-ts>-from-<agent>.md`
2. Write a PARTIAL REPORT at `reports/<agent>.md` capturing WIP state + the question
3. EXIT
4. Orchestrator handles the decision, then spawns a CONTINUATION AGENT with the decision embedded in its prompt — see "Relaunching a dead agent" below.

The continuation agent inherits the dead agent's JSONL (forked by copying to a new UUID in the same encoded-project-dir), so all prior context (including the MSG it sent) is preserved.

## Phase 5 — Monitor (event-stream)

After fanout, run the watcher inside `Monitor`. Every state transition (report landed, message in orchestrator inbox, dead agent, silent log, all-done) lands as a notification in this session within ~2 seconds. No more cron-checking; reactions are deterministic instead of "did I remember to poll?".

```
Monitor({
  description: "parallel-orchestrate watch for session <tag>",
  command: "python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py --session-tag <tag> --watch --silent-min 5",
  persistent: true,
  timeout_ms: 3600000
})
```

**`persistent: true` is required.** Without it, the default 5-minute timeout (or even the 1-hour max) would kill the watcher mid-fanout. `timeout_ms` is ignored when `persistent: true` but the schema requires it; pass `3600000`. Stop the watcher via `TaskStop` if you need to detach manually.

Monitor runs the watcher as a background process — the orchestrator can issue other tool calls in parallel while events stream in. React per the autonomy reaction table below. When the watcher emits `ALL_DONE` and exits, Monitor reports the command's completion and the orchestrator advances to Phase 6.

If the watcher exits without emitting `ALL_DONE` (crashed or killed), do NOT auto-advance to Phase 6. Re-attach with the same `--watch` command — snapshot replay covers any state that landed while detached — and read the watcher's stderr (Monitor saves it to its output file) to diagnose the crash.

For ad-hoc snapshots outside an active `--watch`, `--status` still works.

### Autonomy reaction table

| Event | Auto-act? | Action |
| --- | --- | --- |
| `WATCH_START` | safe | One-line ack in conversation: "watching `<n>` agents, session=`<tag>`". |
| `REPORT <agent>` | safe | Note in conversation: "agent `<agent>` finished, report at `<path>`". Do NOT read the report yet — Phase 6 reads them all. |
| `MSG <agent>` (FYI) | safe | Read the file. If it's an informational notice ("I'm changing the OrderEvent shape, here's the new type"), forward to the named peer's inbox, mirror to `seen/`, summarise in conversation. |
| `MSG <agent>` (decision) | escalate | Surface verbatim to user. Ask: "answer directly / forward to `<peer>` / pause this agent?" Do not write to mailboxes until user decides. |
| `DEAD <agent>` | escalate | Surface the `last_err_tail` (exit code is always `?` because agents are detached subprocesses — the `.err` tail is the diagnostic). Ask: "write partial report manually / relaunch / abort?" Never auto-relaunch — rate-limits, prompt mis-parses, and JSONL mismatches each need different recovery. |
| `SILENT <agent>` | escalate | Cross-check before surfacing: `ps -p <pid>`, `git -C <worktree> status --porcelain`, `ls <session-dir>/reports/`. If PID is alive AND worktree shows uncommitted changes (`M` or `??`), it's almost certainly a `claude` stdout-buffering false positive — wait for the next event. Surface to user only if ALL three cross-checks show no activity. Do NOT auto-poke. See "SILENT false-positive pattern" below. |
| `ALL_DONE` | safe | One-line summary, then transition to Phase 6 ("reading all `<n>` reports now"). |

### SILENT false-positive pattern

The `claude` CLI block-buffers stdout when redirected to a non-TTY file (libc default for non-interactive streams, ~4KB+ before flush). An agent actively editing files via Edit/Write can produce no log growth for `silent_min` minutes while making real progress in the worktree — watcher emits SILENT, agent is fine. Observed twice simultaneously in HyperShield Wave 3 (2026-05-16): both agents triggered SILENT at the 5-minute mark while actively editing files; `git -C <worktree> status --porcelain` immediately disproved the stall.

The autonomy table's 3-step cross-check eliminates 100% of observed false positives:

1. `ps -p <pid>` — process alive
2. `git -C <worktree> status --porcelain` — uncommitted changes present (`M`/`??`)
3. `ls <session-dir>/reports/` — no premature report

If 1 + 2 are positive, ignore the SILENT and continue waiting. The watcher's `scan_silent()` (post-2026-05-16) also does this cross-check at source, so the event won't even emit when uncommitted changes exist — but the cross-check pattern remains the orchestrator's fallback if running against an older watcher.

A clean wrapper fix (e.g., `stdbuf -oL claude ...`) isn't available: macOS doesn't ship `stdbuf` by default, and `claude` is a Mach-O native binary (not Node), so libc-layer buffering hints may not apply. Cross-check is the recommended pattern.

### Distinguishing FYI from decision MSGs

Treat a `MSG` as a **decision** (escalate) if any of:
- body contains a `?` not inside quoted code
- body contains "blocked", "stuck", "should I", "which", "approve", "ok to"
- no specific recipient peer is named

Otherwise treat as **FYI** (auto-forward). **When in doubt, escalate** — over-asking is cheap; auto-deciding a contract question that should have been yours is expensive.

### Re-attach

If you Ctrl+C the `Monitor` mid-fanout (or it errors), agents keep running. Re-attach with the same `--watch` command; snapshot replay re-emits any pending reports and inbox messages so you don't miss the events that landed while detached.

### After a relaunch: ALL_DONE may fire spuriously

The watcher's ALL_DONE heuristic is "report file present at each agent's `report_path`" — not "PID alive." After you relaunch an agent (see below), if the relaunched agent writes to a DIFFERENT report path (e.g., `<agent>-v2.md` instead of `<agent>.md`), the watcher reads the v1 report as "done" and fires ALL_DONE prematurely.

Workarounds:
1. **Overwrite the v1 report path in the relaunched agent's mandate.** Cleanest — the watcher correctly detects the new report.
2. **Ignore the spurious ALL_DONE and poll manually** via `Bash run_in_background`:
   ```bash
   bash -c '
   while kill -0 <NEW_PID> 2>/dev/null; do
     [ -f "<NEW_REPORT_PATH>" ] && exit 0
     sleep 30
   done
   '
   ```

### Relaunching a dead agent

When an agent dies (DEAD event surfaced; user approves relaunch — never auto-relaunch), the script does not yet have a `--relaunch` flag, so the workflow is manual:

1. Find the dead JSONL: `jq -r '.spawns[] | select(.task_name == "<agent>") | .jsonl_path' .tmp/parallel-orchestrate/<tag>/manifest.json`
2. New UUID: `NEW_UUID=$(uuidgen | tr 'A-Z' 'a-z')`
3. Fork the JSONL (preserves prior context including any MSGs the dead agent sent):
   ```bash
   cp <dead-jsonl> $(dirname <dead-jsonl>)/${NEW_UUID}.jsonl
   ```
4. cd to the worktree (so `claude --resume`'s encoded-cwd resolution finds the new JSONL).
5. Launch detached, with `<continuation-prompt>` containing the decision/context the dead agent was waiting on:
   ```bash
   nohup claude --resume "$NEW_UUID" --model <m> --dangerously-skip-permissions \
     -p "$(cat continuation-prompt.txt)" \
     > .tmp/parallel-orchestrate/<tag>/logs/<agent>-r2.out \
     2> .tmp/parallel-orchestrate/<tag>/logs/<agent>-r2.err \
     < /dev/null &
   NEW_PID=$!
   ```
6. Update `manifest.json` so Phase 7 cleanup correctly reaps the new process — swap `pid`, `uuid`, `jsonl_path`, `log_out`, `log_err`; save originals as `pid_original` etc.

The continuation prompt MUST embed any decision the dead agent was waiting on — never make the relaunched agent re-enter the mailbox-wait state that killed its predecessor.

## Phase 6 — Reconcile

1. **Read every report in full.** No skim. Each report should declare: what was implemented, what was skipped + why, files touched, test status, follow-ups.
2. **Surface findings inline for the user** — one paragraph per agent.
3. **Worktree mode (default):** for each agent in dependency order, `git merge --no-ff feature/<name>`. Resolve conflicts. After each merge, run typecheck + tests. Revert that merge and ask the user if red. Leave the worktrees on disk — `git worktree remove` happens in Phase 7.
   - Alternative: push each `feature/<name>` branch and open a PR per agent (lets CodeRabbit / ultrareview run per branch). Skip the local merge if going PR-per-feature.
4. **Shared mode:** run typecheck + tests. All agents already wrote to the same tree.
5. **Commit per agent** (if merging locally) with mandate as message: `feat(payments): <one-line>` + a paragraph from the report.
6. **Compile follow-ups** from every report into one TODO list for the next wave or a follow-up issue.

## Phase 7 — Cleanup

```bash
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag <tag> --cleanup [--remove-worktrees] [--purge-session-dir]
```

Cleanup kills any lingering PIDs (SIGTERM, then SIGKILL after 0.5s), removes the forked JSONLs, optionally removes worktrees, optionally purges the session dir. Reports + mailbox + manifest stay by default so you can revisit a decision later.

**Don't `--remove-worktrees` if PRs are open** against those branches — git worktree removal won't delete the branch, but you lose the on-disk working copy.

## Common mistakes

| ❌ Wrong | ✅ Right |
|---------|---------|
| Skip critical review, fan out the moment you've decomposed | Read recon adversarially before fanout — gaps and contradictions raised to user first |
| Two agents own overlapping files, "they'll figure it out via mailbox" | Mailbox is for interface contracts, not shared edits. Never overlap files in the same wave. |
| Vague mandate: "improve the payments code" | Specific: "implement §3.2 in src/payments/**, tests passing, report at <path>" |
| Bundle two concerns: "implement X and clean up Y" | One mandate per agent. Forks are cheap; spawn another for Y |
| Tell every fork the full project background in its prompt | Recon happens once in the orchestrator; forks inherit via JSONL — keep prompts tight |
| Land shared types/migrations *during* fanout | Land them as pre-work, commit, then fan out from that commit |
| Fan out 2 items because "it might save time" | 2 isn't worth ceremony — sequential is fine. 3+ before fanout |
| Skim agent reports at reconcile | Read every report in full — reconcile is where the orchestrator earns its keep |
| Merge an agent's branch and skip the test run | Run typecheck + tests after every merge; revert if red |
| Let an agent guess past a missing dep or unclear spec | Each mandate includes explicit stop-and-report-partial criteria; agents message orchestrator before stopping |
| Assign Opus to every agent by default | Score each task first. Mechanical tasks with explicit instructions are Sonnet. Pure read/report tasks are Haiku. |
| Stash before fanout without checking `??` lines | `git stash` skips untracked files. New source files won't appear in worktrees. Use `git stash -u` or commit them first. |
| Omit `--parent` when spawning | The script refuses to run without it — the orchestrator must explicitly designate the parent JSONL |
| Forget the orchestrator has its own mailbox | Agents write to `mailbox/orchestrator/inbox/` when blocked. The `--watch` stream surfaces these as `MSG` events automatically — react per the autonomy table, don't poll manually. |
| Skip `--watch` and revert to `--status` polling because Monitor feels heavy | The whole point of Phase 5 is event-stream. If you're cron-checking, re-read Phase 5 and start over with `--watch`. |
| Reuse a session-tag for a second fanout while the first is still around | Pick a new tag, or `--cleanup` the old one first. The script refuses if the manifest exists. |
| Spawn forks without propagating discipline | The script's wrapper already prepends `invoke karpathy-guidelines` to every prompt; verify it survives if you customize the wrapper |
