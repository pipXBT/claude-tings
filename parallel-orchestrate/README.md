# parallel-orchestrate

A Claude Code skill that decomposes a design document into independent features and spawns one agent per feature. Each agent runs in its own git worktree on a `feature/<name>` branch, with a file-based mailbox so agents can DM each other and the orchestrator while running. The orchestrator (the session you invoke from) stays live, brokers cross-agent messages, and reconciles at the end.

Terminal-agnostic: works in iTerm2, Terminal.app, tmux, plain SSH — no terminal multiplexer required. Agents run as background processes; output goes to log files.

## Why

A design doc with five independent features is five tasks worth of context-switching for a single session. This skill turns that into one orchestrator session plus N background agents — each on its own feature branch (so CodeRabbit, ultrareview, and other branch-scoped review tools work unchanged), each starting with the orchestrator's recon as live conversation context. Reconcile happens once, per-branch, via merge or PR.

## When to use

- Design doc with three or more features that don't share files
- Each feature wants its own PR / branch for review tooling
- Work big enough that a single session would otherwise context-switch for an hour

## When NOT to use

- Single linear task or task that fits in one file
- Codebase has heavy dynamic wiring (Rails autoload, Django signals, WordPress hooks) needing single-author awareness
- Spec is half-baked — fanout amplifies bad specs; tighten the spec first
- You expect agents to literally watch each other's terminal output — this skill uses async file mailboxes, not shared TTYs

## Requirements

- `claude` CLI on PATH (Claude Code)
- `git` on PATH (for the default `worktree` mode)
- A git repo with a clean working tree (or willingness to commit/stash before fanning out)
- An existing Claude Code session in the cwd (the skill forks its JSONL)
- Python 3.8+

No multiplexer required. Works in any terminal emulator.

## Install

Part of the [`pipXBT/claude-tings`](https://github.com/pipXBT/claude-tings) collection.

**Whole collection:**

```bash
git clone https://github.com/pipXBT/claude-tings.git ~/code/claude-tings
cd ~/code/claude-tings && ./install.sh
```

**Just this skill:**

```bash
git clone https://github.com/pipXBT/claude-tings.git ~/code/claude-tings
mkdir -p ~/.claude/skills
ln -s ~/code/claude-tings/parallel-orchestrate ~/.claude/skills/parallel-orchestrate
chmod +x ~/code/claude-tings/parallel-orchestrate/scripts/spawn-parallel.py
```

Restart your Claude Code session. Verify by asking `what skills do you have?` — `parallel-orchestrate` should appear.

## Use

Inside any Claude Code session:

```
> Read docs/feature-x-spec.md and use parallel-orchestrate to implement it.
```

Claude reads the doc, talks through the work in this session (recon), proposes one agent per feature (which files each owns, which model fits, where inter-feature contracts live), asks you to confirm, lands any shared pre-work, then runs `scripts/spawn-parallel.py` to spawn one background agent per feature on its own `feature/<name>` branch.

The orchestrator polls `.tmp/parallel-orchestrate/<tag>/` for reports and its own inbox, brokering cross-agent messages as they arrive. When all reports land, the orchestrator merges each branch (or pushes them as PRs), runs your test suite per merge, and commits per-agent.

## Layout per fanout

Everything lives under `.tmp/parallel-orchestrate/<session-tag>/`:

```
.tmp/parallel-orchestrate/<tag>/
├── manifest.json                   # UUIDs, PIDs, branches, worktree paths
├── reports/
│   └── <agent>.md                  # final report per agent
├── logs/
│   ├── <agent>.out                 # stdout
│   ├── <agent>.err                 # stderr
│   └── <agent>.pid                 # pid file
└── mailbox/
    ├── orchestrator/{inbox,seen,outbox}/
    └── <agent>/{inbox,seen,outbox}/
```

Worktrees live siblings to the repo at `<repo>/../<repo>-worktrees/<task-name>` on branch `feature/<task-name>`.

## Mailbox protocol

Each agent (and the orchestrator) has `mailbox/<name>/{inbox,seen,outbox}/`. To message a peer:

```
write  .tmp/parallel-orchestrate/<tag>/mailbox/<recipient>/inbox/<UTC>-from-<sender>.md
mirror .tmp/parallel-orchestrate/<tag>/mailbox/<sender>/outbox/<UTC>-to-<recipient>.md
```

Recipient polls its `inbox/` between major work steps, moves processed messages to `seen/`. The orchestrator brokers — answering, forwarding, or escalating to the user.

Use it for **interface contracts and blocking questions**, not status chatter. Reports cover status.

## Modes

| Mode | Behaviour | When to pick |
|------|-----------|--------------|
| `worktree` (default) | Each agent in its own `git worktree` on `feature/<task-name>`. Reconcile = `git merge` per branch or PR per branch. | Default. Anything where you want per-feature review or branch isolation. |
| `shared` | All agents in the orchestrator tree; no branches, no worktrees. | Only when file-ownership is strict, you trust the boundaries, and want one combined PR. |

## Inspect / monitor

```bash
# one-shot snapshot — alive procs, reports landed, orchestrator inbox depth
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag <tag> --status

# live TUI dashboard — open in a separate terminal window/tab; refreshes every 2s
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag <tag> --dashboard

# event-stream for the orchestrator session (Monitor tool)
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag <tag> --watch --silent-min 5

# tail a specific agent's log
tail -f .tmp/parallel-orchestrate/<tag>/logs/<agent>.out

# orchestrator's brokering queue
ls .tmp/parallel-orchestrate/<tag>/mailbox/orchestrator/inbox/
```

`--dashboard` shows per-agent state (● RUN / ◐ SILENT / ✓ REPORT / ✗ DEAD), runtime, mailbox depth, and worktree `M=… ??=…` counts; same SILENT cross-check as the watcher (uncommitted edits disprove a false-positive stall). Requires the `rich` Python library (`pip3 install rich`).

## Cleanup

```bash
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag <tag> --cleanup [--remove-worktrees] [--purge-session-dir]
```

Kills any lingering PIDs (SIGTERM, then SIGKILL after 0.5s), removes forked JSONLs, optionally removes worktrees, optionally purges the session dir. Reports + mailbox stay by default.

## Layout

```
parallel-orchestrate/
├── SKILL.md                              # phases the orchestrator follows
├── README.md                             # this file
├── scripts/
│   └── spawn-parallel.py                 # JSONL fork + worktree + bg subprocess
└── references/
    └── spawn-script-internals.md         # debug + extend guide for the script
```

## License

MIT — see [`../LICENSE`](../LICENSE) at the collection root.
