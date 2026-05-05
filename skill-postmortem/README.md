# skill-postmortem

A Claude Code skill that reviews the effectiveness of *another* skill against actual session evidence and proposes evidence-backed edits to its `SKILL.md`, scripts, or references — with the user approving each edit before it lands.

## Why

Skills don't get better on their own. The first version of any skill encodes assumptions that turn out to be wrong on first contact with reality (CLI shapes, path conventions, edge cases). Without a structured review you either:

- Edit reactively in the moment (loses the cross-session pattern)
- Never edit (skills calcify with broken instructions)
- Let Claude "self-improve" autonomously (skills drift in unintended directions)

`skill-postmortem` is the third path: gather evidence across many sessions, propose evidence-backed edits, **user approves each before it lands**.

## When to use

- A skill misbehaved during real use and you want to know why
- A skill has been used multiple times and warrants a structured review
- You suspect a skill's `description` is misfiring (wrong invocations, missed invocations)
- You want to clean up a skill before publishing it more widely

## When NOT to use

- Skill has fewer than two or three real invocations — not enough evidence
- You already know the exact edit — go straight to editing the SKILL.md
- Plugin-namespaced skill (`<plugin>:<name>`) — edit upstream and open a PR

## Install

Part of the [`pipXBT/claude-tings`](https://github.com/pipXBT/claude-tings) collection. See top-level [README](../README.md) for collection install, or:

```bash
git clone https://github.com/pipXBT/claude-tings.git ~/code/claude-tings
ln -s ~/code/claude-tings/skill-postmortem ~/.claude/skills/skill-postmortem
```

## Use

Inside any Claude Code session:

```
> Run skill-postmortem on parallel-orchestrate.
```

or

```
> Review the effectiveness of skill X.
```

Claude reads the most recent JSONLs that invoked the skill, categorizes friction across eight categories (A–H), confidence-ranks each finding, and proposes specific edits. You approve each edit before it lands.

## Output shape

```
Found 7 sessions invoking parallel-orchestrate.

Friction summary:
  Category B (wrong CLI shape):      2 high, 1 medium
  Category E (hardcoded assumption): 1 high
  Category F (manual workaround):    1 high, 2 medium
Total: 4 high-confidence edits proposed.

Edit 1 of 4 — Category E (hardcoded assumption):
  Finding: encode_project_path doesn't handle paths with spaces.
  Evidence: session 6afdc4dd... — fork landed JSONL at wrong dir.
  Proposed diff:
    - re.sub(r"[/.]", "-", ...)
    + re.sub(r"[^A-Za-z0-9]", "-", ...)
  Why not bigger: matches Claude Code's actual encoding.

[edits 2–4]

Apply 1, 3, 4? Skip 2? Pick a subset?
```

## Categories

| Code | Name | Symptom |
|------|------|---------|
| A | Spec gap | Claude asked a clarifying question the skill should have answered |
| B | Wrong CLI / API shape | Tool errors, "Unknown action", "command not found" |
| C | Trigger phrase miss | User had to name the skill explicitly |
| D | Scope ambiguity | Claude did too much / too little, user redirected |
| E | Hardcoded assumption | Script broke on a real environment (paths, OS, versions) |
| F | Manual workaround | User wrote inline code instead of using the bundled script |
| G | Preflight too strict / too loose | Aborts on cases that should run, or runs through cases it should catch |
| H | Description-trigger collision | Skill fires when it shouldn't, or doesn't fire when it should |

## Layout

```
skill-postmortem/
├── SKILL.md     # phases the postmortem follows
└── README.md    # this file
```

No bundled scripts. Operations (find sessions, grep, read, propose edit) are native to Claude.

## License

MIT — see [`../LICENSE`](../LICENSE) at the collection root.
