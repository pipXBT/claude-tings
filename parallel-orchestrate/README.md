# parallel-orchestrate

A Claude Code skill that takes a design or implementation document, identifies which parts can run independently, then fans out one **Claude Opus** agent per work unit into its own **cmux** workspace tab. Each agent inherits the orchestrator session's recon as live conversation history (via JSONL fork), works in its own **git worktree**, and writes a structured report. The orchestrator session reconciles.

**Borrows** the JSONL-fork-inherits-context trick from [`cc-fork`](https://github.com/STRML/cc-skills/blob/main/bin/cc-fork) and the recon→fanout→reconcile shape from [`/code-cleanup`](https://github.com/STRML/cc-skills/blob/main/commands/code-cleanup.md). **Adds** cmux-aware spawning so each fork is a visible sidebar tab instead of a captured stdout stream.

## Why

Built-in `Task`/`Agent` spawns start blank — they re-read your codebase and re-derive context every time. `cc-fork` solves that for headless `-p` forks but leaves you watching stdout. This skill solves it for **interactive Opus agents you can actually see and intervene in**, by stitching `cc-fork`'s JSONL trick to `cmux new-workspace`. Per-agent worktrees mean five Opus agents editing the same repo in parallel without conflicts.

Use it when:
- You have a design doc with several independent feature buckets
- The work is big enough that you'd otherwise context-switch between sub-tasks for an hour
- You're already living in cmux and want each agent's progress in its own tab

Don't use it when:
- The task is linear (no parallelism gain)
- The codebase has heavy dynamic wiring (Rails autoload, Django signals, etc.) that needs single-author awareness
- You're not in cmux — the visibility is the point; outside cmux just use `cc-fork` directly

## Requirements

- macOS with [cmux](https://cmux.com) running (`brew install --cask cmux`)
- `claude` CLI on PATH (Claude Code)
- A git repo with a clean working tree (or willingness to commit before fanning out)
- An existing Claude Code session in the cwd (the skill forks its JSONL)
- Python 3.8+

## Install

This skill ships as part of the [`pipXBT/claude-tings`](https://github.com/pipXBT/claude-tings) skills collection.

**One-shot (installs every skill in the collection):**

```bash
git clone https://github.com/pipXBT/claude-tings.git ~/code/claude-tings
cd ~/code/claude-tings && ./install.sh
```

**Just this skill:**

```bash
git clone https://github.com/pipXBT/claude-tings.git ~/code/claude-tings
mkdir -p ~/.claude/skills
ln -s ~/code/claude-tings/parallel-orchestrate ~/.claude/skills/parallel-orchestrate
chmod +x ~/code/claude-tings/parallel-orchestrate/scripts/spawn-cmux.py
```

Restart your Claude Code session — skills are discovered at session start. Verify with `claude` running in any project: ask `what skills do you have?` and `parallel-orchestrate` should appear.

### Updating

```bash
cd ~/code/claude-tings
git pull
```

Symlinks pick up changes automatically.

## Use

Inside a Claude Code session running in cmux, in a git repo:

```
> Read docs/feature-x-spec.md and use parallel-orchestrate to implement it across opus agents in cmux.
```

Claude reads the doc, talks through the work in this session (recon), proposes a wave-1 split (which items go to which agents and what files each owns), asks you to confirm, lands any shared pre-work, then runs `scripts/spawn-cmux.py` to spawn one Opus agent per wave-1 task into its own cmux workspace tab.

You watch the tabs fill in. Each agent ends by writing a report to `.tmp/parallel-orchestrate/<tag>/reports/<agent>.md` and pinging `cmux notify`. The orchestrator session reads every report, merges the worktree branches, runs your test suite, and commits per-agent.

## Modes

- `worktree` (default): one `git worktree` per agent. Reconcile = `git merge`. Conflict-free in normal cases.
- `shared`: agents share the orchestrator's tree. Faster reconcile, but requires strict file-ownership boundaries; one bad agent corrupts the tree for everyone.
- `dry-run`: no edits applied; agents write proposed patches to their reports. Reconcile reviews and applies the approved ones. Use on fragile codebases or first time on a new repo.

## Layout

```
parallel-orchestrate/
├── SKILL.md                              # what Claude reads when the skill triggers
├── README.md                             # this file
├── scripts/
│   └── spawn-cmux.py                     # JSONL fork + worktree + cmux launch
└── references/
    └── spawn-script-internals.md         # debug + extend guide for the script
```

## License

MIT — see [`../LICENSE`](../LICENSE) at the collection root. The cc-skills work this builds on is also MIT.
