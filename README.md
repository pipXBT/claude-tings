# agent-shenanigans

A personal collection of agent skills for [Claude Code](https://claude.com/claude-code)
**and** [Grok Build](https://x.ai) (xAI's CLI).

Each subdirectory is an independent skill: a `SKILL.md` (with YAML frontmatter that
tells the agent when to invoke it) plus any supporting scripts and reference docs the
skill needs. Install one, several, or all of them — into either CLI, or both.

> Renamed from `claude-tings`. The old GitHub URL auto-redirects, but update any
> local clones to `agent-shenanigans`.

## Skills in this repo

| Skill | What it does | CLIs |
|-------|--------------|------|
| [debate](./debate/) | Multi-AI plan review before writing code. Sends a plan to a panel of independent reviewers running in parallel, surfaces hidden assumptions and failure modes, debates contradictions, and produces a consensus `APPROVED`/`REVISE` verdict with SHA-verified plans. Ships a Claude Code variant (acpx + external CLIs like Codex/Gemini/Opus) **and** a Grok-native variant (Grok personas via `spawn_subagent`). | Claude + Grok |
| [parallel-orchestrate](./parallel-orchestrate/) | Read a design doc, decompose into parallelizable work units, then fan out one Opus agent per unit into its own [cmux](https://cmux.com) workspace tab. Each fork inherits the orchestrator's recon as live conversation context (via JSONL fork) and works in an isolated git worktree. | Claude |
| [skill-postmortem](./skill-postmortem/) | Review the effectiveness of *another* skill against actual session evidence. Reads JSONLs where the skill was invoked, categorizes friction across eight categories, confidence-ranks findings, and proposes evidence-backed edits — user approves each before it lands. | Claude |

More to come.

## Two CLIs, one repo

Both Claude Code and Grok Build load skills from `SKILL.md`-shaped directories, but
from different roots:

| CLI         | User skills dir      | Also reads          |
|-------------|----------------------|---------------------|
| Claude Code | `~/.claude/skills/`  | —                   |
| Grok Build  | `~/.grok/skills/`    | `~/.claude/skills/` |

Grok Build dedupes skills **by name**, with `~/.grok/skills/` winning over
`~/.claude/skills/`. So a skill can ship two variants:

- `SKILL.md` → the **Claude Code** variant → `~/.claude/skills/<name>/`
- `SKILL.grok.md` → the **Grok-native** variant → `~/.grok/skills/<name>/SKILL.md`

Claude Code sees only its variant; Grok Build sees both but the `~/.grok/` one wins.
A skill with no `.grok` variant is environment-agnostic — it lives in
`~/.claude/skills/` and Grok reads it there via compatibility.

The repo root also carries an [`AGENTS.md`](./AGENTS.md) (the cross-tool agent guide,
read natively by Grok Build) with `CLAUDE.md` symlinked to it so Claude Code reads
the same instructions.

## Install

Skills are symlinked in, so `git pull` keeps them current.

```bash
git clone https://github.com/pipXBT/agent-shenanigans.git ~/code/agent-shenanigans
cd ~/code/agent-shenanigans
```

### `install.sh` — both CLIs (recommended)

```bash
./install.sh                 # every skill, both ~/.claude/skills and ~/.grok/skills
./install.sh --target claude # only Claude Code
./install.sh --target grok   # only Grok Build (installs Grok-native variants)
./install.sh debate          # just one skill
./install.sh --dry-run       # show what would happen, change nothing
```

`install.sh` symlinks each skill into the right directory per target, installs any
`SKILL.grok.md` as the Grok variant, and `chmod +x`'s bundled scripts. Re-run after
`git pull` to pick up new skills.

### Or symlink by hand

```bash
# Claude Code
mkdir -p ~/.claude/skills
ln -s ~/code/agent-shenanigans/debate ~/.claude/skills/debate

# Grok Build (native variant)
mkdir -p ~/.grok/skills/debate
ln -s ~/code/agent-shenanigans/debate/SKILL.grok.md ~/.grok/skills/debate/SKILL.md
```

### Verify

Restart any running `claude` / `grok` session (skills are scanned at session start),
then ask: *"What skills do you have available?"* The skills you linked should appear
by name.

## Updating

```bash
cd ~/code/agent-shenanigans
git pull          # symlinks pick up changes automatically
./install.sh      # only needed to wire up newly-added skills
```

## Removing a skill

```bash
rm ~/.claude/skills/<skill-name>          # Claude Code (symlink only; repo untouched)
rm -rf ~/.grok/skills/<skill-name>        # Grok Build
```

## Adding your own skills

See [`AGENTS.md`](./AGENTS.md) for the full convention. Minimum: a directory with a
`SKILL.md` whose frontmatter `description` is packed with trigger phrases — that's
what both CLIs read to decide when to invoke it. Add a `SKILL.grok.md` alongside it
only if the skill needs different behavior in Grok Build.

## Credits

- The [`debate`](./debate/) skill is a personal adaptation of Sam Reed's
  ([STRML](https://github.com/STRML)) [`cc-debate`](https://github.com/STRML/cc-debate)
  plugin and [`cc-skills`](https://github.com/STRML/cc-skills). The upstream plugin
  remains the canonical implementation of the `/debate:*` commands; this repo vendors a
  customized reviewer panel and a Grok-native port.

## License

[MIT](./LICENSE). Do whatever you want; no warranty.
