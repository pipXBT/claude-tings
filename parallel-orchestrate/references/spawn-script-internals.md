# spawn-cmux.py internals

Read this only when extending the script or debugging an unexpected behaviour. The SKILL.md gives you the public interface.

## What it does, in order

1. **Preflight.** Verifies `CMUX_WORKSPACE_ID` is set, `cmux` and `claude` are on PATH, and (for worktree mode) the cwd is inside a git repo.
2. **Locate parent JSONL.** Reads `~/.claude/projects/<encoded-cwd>/`. The encoded cwd is the absolute path with `/` and `.` replaced by `-`. Picks the largest .jsonl in that dir as the parent — sidecar files are tiny, the live conversation is huge.
3. **Per task:**
   - Generate a v4 UUID for the fork.
   - In worktree mode: `git worktree add -b parallel/<tag>/<name> <repo>/../<repo>-worktrees/<tag>/<name>`.
   - Compute the target cwd's encoded project dir (`~/.claude/projects/<encoded-target-cwd>/`) and `mkdir -p` it.
   - Copy parent JSONL → `<encoded-target-cwd>/<uuid>.jsonl`. **This is the load-bearing step**: `claude --resume <uuid>` resolves against the *cwd of the launching shell*, not the parent's cwd. If the JSONL isn't in the new cwd's project dir, --resume fails with "session not found".
   - Build a shell command: `cd <wt> && claude --resume <uuid> --model opus --dangerously-skip-permissions '<prompt>'`.
   - `cmux new-workspace --command "<that command>"`.
   - Parse the workspace ref from cmux output. If found, `cmux rename-workspace --workspace <ref> '<tag>:<name>'` so the sidebar tab is human-readable.
4. **Manifest.** Write `.tmp/parallel-orchestrate/<tag>/manifest.json` listing every fork's UUID, target cwd, branch, workspace ref, and JSONL path. The cleanup pass and the orchestrator's monitoring read this.
5. **Status.** Push a `cmux set-status orchestrate "<tag>: N agent(s) in flight"` so the orchestrator's own sidebar tab reflects state.

## Cleanup

`--cleanup --session-tag <tag>` reads the manifest and reverses each step: removes the forked JSONL files, closes the cmux workspaces, and (with `--remove-worktrees`) removes the worktrees. Reports stay by default — pass `--purge-session-dir` to wipe them too.

## Why permissions are `--dangerously-skip-permissions`

Forks are non-interactive in the sense that the orchestrator can't easily approve every Edit/Write/Bash. Earlier versions used `--permission-mode acceptEdits`, but that still prompts for `Bash` and other non-edit tools (e.g., `pnpm install`, `git commit`, network fetches), which silently stalled agents that needed those primitives — the prompt fires inside the agent's cmux tab where nobody is watching to approve.

`--dangerously-skip-permissions` removes ALL approval prompts so the agent can run end-to-end without intervention. This is acceptable in worktree mode because each fork's edits are isolated to a sibling working tree branched from a known substrate; the orchestrator inspects every commit at reconcile before merging. In `shared` mode the blast radius is wider — consider whether the agents' mandates are tight enough to justify it. In `dry-run` mode the agents shouldn't be executing anyway, so the flag is harmless.

If you want stricter permissions, edit the `claude_part` line in `spawn_one()` to use `--permission-mode acceptEdits` (file edits auto-approved, other tools prompt) or drop the flag entirely (everything prompts). Either way, the agent's tab needs human attention; the "set it and forget it" property is lost.

## Why we do not use cc-fork directly

`cc-fork` (STRML/cc-skills) does the same JSONL snapshot, but launches each fork via `subprocess.run(claude --resume <uuid> -p "task")` — capturing stdout, no terminal. We need each fork visible as a cmux workspace tab so the user can watch progress and intervene. The launching mechanism is incompatible; the snapshotting trick is the same. If you have cc-fork installed, you can run it side-by-side for the headless cases.

## Common failures and fixes

**"no Claude session dir at …".** The orchestrator's cwd has never had a Claude session. Run `claude` once in this dir first.

**"session not found" inside a fork.** The JSONL didn't land in the right project dir. Check the worktree path is what you expect, and that `~/.claude/projects/<encoded-worktree-path>/<uuid>.jsonl` exists. Encoded path: `/Users/x/repo-worktrees/tag/name` → `-Users-x-repo-worktrees-tag-name`.

**Workspace ref empty in manifest.** The script couldn't parse cmux's output. The workspace was still created — visible in the sidebar — but cleanup won't be able to close it programmatically. You can `cmux list-workspaces` to find it and close it manually. Update the parsing in `cmux_new_workspace()` if cmux's output format changes.

**Worktree already exists.** Means a previous fanout with the same tag wasn't cleaned up. Run `--cleanup --remove-worktrees --session-tag <tag>`, or pick a new tag.

**`git worktree add` fails with detached HEAD or pathspec.** The current HEAD probably has uncommitted changes that conflict, or the branch already exists. The script always creates a fresh branch (`-b parallel/...`); if that branch exists, it's leftover from an aborted run — `git branch -D parallel/<tag>/<name>` and retry.

**Forks don't see parent context.** Verify the parent JSONL was actually copied:
```bash
ls -la ~/.claude/projects/<encoded-target-cwd>/
```
If empty, the encode step (replace `/` and `.` with `-`) probably differs between the script and Claude Code. Run `python3 -c "from pathlib import Path; import re; print(re.sub(r'[/.]', '-', str(Path('<your-target>').resolve())))"` and compare.

## Extending

- **Different model per agent.** Replace `--model` with a per-task override: parse `name:model:prompt` instead of `name:prompt`.
- **Different cwd per agent (non-worktree).** Add a `--target-cwd` per task. The JSONL copy logic already handles arbitrary cwds.
- **Initial input via stdin.** `claude --resume <uuid>` accepts a positional prompt; if you want the fork to start with a pre-loaded file context, pass `--print-and-loop` or use `cmux send` to type into the surface after launch.
- **Wait for all forks before returning.** The script currently spawns and exits. To block, poll for report files in `.tmp/parallel-orchestrate/<tag>/reports/` or `cmux read-screen` each surface looking for an exit marker. A blocking flag `--wait-for-reports N` would be a small addition.
