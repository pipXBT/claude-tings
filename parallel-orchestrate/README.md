# parallel-orchestrate

A Claude Code skill that decomposes a design document into independent work units, runs one Claude Opus agent per unit in its own cmux workspace tab and git worktree, and reconciles the parallel output in the orchestrator session. Each agent inherits the orchestrator's recon as live conversation context, so forks start writing code instead of re-deriving project background.

## Why

A design doc with five independent feature buckets is five tasks worth of context-switching for a single session. This skill turns that into one orchestrator session plus N parallel agents — each visible as a cmux tab, each in its own worktree, each starting with the same shared understanding of the spec. Reconcile happens once at the end, not constantly throughout.

## When to use

- Design doc with three or more work units that don't share files
- Work big enough that a single session would otherwise context-switch for an hour
- You're running inside a cmux terminal and want each agent's progress in its own tab

## When NOT to use

- Single linear task or task that fits in one file
- Codebase has heavy dynamic wiring (Rails autoload, Django signals, WordPress hooks) that needs single-author awareness
- Spec is half-baked — fanout amplifies bad specs; tighten the spec first
- Not in cmux — the visibility-as-tabs benefit goes away

## Requirements

- macOS with [cmux](https://cmux.com) running (`brew install --cask cmux`)
- `claude` CLI on PATH (Claude Code)
- A git repo with a clean working tree (or willingness to commit before fanning out)
- An existing Claude Code session in the cwd (the skill forks its JSONL)
- Python 3.8+

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
chmod +x ~/code/claude-tings/parallel-orchestrate/scripts/spawn-cmux.py
```

Restart your Claude Code session. Verify by asking `what skills do you have?` — `parallel-orchestrate` should appear.

### Updating

```bash
cd ~/code/claude-tings
git pull
```

Symlinks pick up changes automatically.

## Use

Inside a Claude Code session running in cmux:

```
> Read docs/feature-x-spec.md and use parallel-orchestrate to implement it.
```

Claude reads the doc, talks through the work in this session (recon), proposes a wave-1 split (which items go to which agents and what files each owns), asks you to confirm, lands any shared pre-work, then runs `scripts/spawn-cmux.py` to spawn one Opus agent per wave-1 task into its own cmux workspace tab.

You watch the tabs fill in. Each agent ends by writing a report to `.tmp/parallel-orchestrate/<tag>/reports/<agent>.md` and pinging `cmux notify`. The orchestrator session reads every report, merges the worktree branches, runs your test suite, and commits per-agent.

## Modes

| Mode | Behaviour | When to pick |
|------|-----------|--------------|
| `worktree` (default) | Each agent in its own `git worktree`. Reconcile = `git merge`. | Any fanout where agents could touch overlapping files |
| `shared` | All agents share the orchestrator's tree. Faster reconcile (no merge). | When file-ownership boundaries are strict and you trust them |
| `dry-run` | No edits applied; agents propose patches in their reports. Reconcile reviews and applies the approved ones. | Fragile codebases or first-time use on a new repo |

## Layout

```
parallel-orchestrate/
├── SKILL.md                              # phases the orchestrator follows
├── README.md                             # this file
├── scripts/
│   └── spawn-cmux.py                     # JSONL fork + worktree + cmux launch
└── references/
    └── spawn-script-internals.md         # debug + extend guide for the script
```

## License

MIT — see [`../LICENSE`](../LICENSE) at the collection root.
