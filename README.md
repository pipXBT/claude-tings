# claude-tings

A personal collection of [Claude Code](https://claude.com/claude-code) skills.

Each subdirectory is an independent skill: a `SKILL.md` (with YAML frontmatter that tells Claude when to invoke it) plus any supporting scripts and reference docs the skill needs. Install one, several, or all of them.

## Skills in this repo

| Skill | What it does |
|-------|--------------|
| [parallel-orchestrate](./parallel-orchestrate/) | Read a design doc, decompose into parallelizable work units, then fan out one Opus agent per unit into its own [cmux](https://cmux.com) workspace tab. Each fork inherits the orchestrator's recon as live conversation context (via JSONL fork) and works in an isolated git worktree. |
| [skill-postmortem](./skill-postmortem/) | Review the effectiveness of *another* skill against actual session evidence. Reads JSONLs where the skill was invoked, categorizes friction across eight categories, confidence-ranks findings, and proposes evidence-backed edits — user approves each before it lands. Methodology adapted from STRML's `session-learnings`. |

More to come.

## Install

Skills live at `~/.claude/skills/<skill-name>/`. There are two ways to wire that up:

### Option A — symlink individual skills (recommended)

Clone once, symlink the skills you want. Updates are `git pull` away.

```bash
git clone https://github.com/pipXBT/claude-tings.git ~/code/claude-tings

# Symlink the skill(s) you want
mkdir -p ~/.claude/skills
ln -s ~/code/claude-tings/parallel-orchestrate ~/.claude/skills/parallel-orchestrate

# Some skills bundle scripts that need to be executable
chmod +x ~/code/claude-tings/parallel-orchestrate/scripts/*.py 2>/dev/null || true
```

### Option B — `install.sh` (one-shot, all skills)

```bash
git clone https://github.com/pipXBT/claude-tings.git ~/code/claude-tings
cd ~/code/claude-tings
./install.sh
```

`install.sh` symlinks every skill subdirectory under `~/.claude/skills/` and chmods any bundled scripts. Re-run it after `git pull` to pick up new skills.

### Verify

Restart any running `claude` session (skills are scanned at session start), then ask:

> What skills do you have available?

The skills you symlinked should appear by name, with their descriptions matching what's in each `SKILL.md` frontmatter.

## Updating

```bash
cd ~/code/claude-tings
git pull
```

Symlinks pick up changes automatically. New skills added to the repo? Either symlink them by hand or re-run `install.sh`.

## Removing a skill

```bash
rm ~/.claude/skills/<skill-name>   # removes the symlink only; original stays in the repo
```

## Adding your own skills

Each skill is a directory containing at minimum a `SKILL.md` with YAML frontmatter:

```markdown
---
name: my-skill
description: "Use when ... [trigger phrases]. [What the skill does, in one sentence.]"
---

# my-skill

[The instructions Claude follows when this skill is invoked.]
```

The `description` is what Claude reads to decide whether to invoke the skill — pack it with trigger phrases and a clear use-case statement. Optional layout for skills that ship code:

```
my-skill/
├── SKILL.md
├── README.md            # optional, for humans browsing on GitHub
├── scripts/             # optional, executable helpers
└── references/          # optional, docs the skill loads only when needed
```

## License

[MIT](./LICENSE). Do whatever you want; no warranty.
