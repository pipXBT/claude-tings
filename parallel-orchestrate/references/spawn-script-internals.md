# spawn-parallel.py internals

Read this only when extending the script or debugging unexpected behaviour. SKILL.md gives you the public interface.

## What it does, in order

1. **Preflight.** Verifies `claude` (and `git`, in worktree mode) on PATH. Refuses to run without `--parent <uuid>` — the orchestrator must designate the parent JSONL explicitly. The largest-JSONL heuristic from cc-fork is intentionally disabled here because active repos accumulate many large historical sessions and auto-pick is wrong often enough to disallow.
2. **Locate parent JSONL.** Reads `~/.claude/projects/<encoded-cwd>/<parent-uuid>.jsonl`. The encoded cwd replaces every non-alphanumeric character (including `_`, `/`, `.`) with `-`. Mismatch the encoding and the JSONL lands in a directory `claude --resume` will never look in.
3. **Per task:**
   - Validate the task name matches `[a-z0-9][a-z0-9_-]{0,40}` — it becomes both a git branch and a worktree dir.
   - In `worktree` mode: check `feature/<task-name>` doesn't already exist (refuse rather than silently reuse), then `git worktree add -b feature/<task-name> <repo>/../<repo>-worktrees/<task-name>`.
   - Generate a v4 UUID for the fork.
   - Compute the target cwd's encoded project dir (`~/.claude/projects/<encoded-target-cwd>/`) and `mkdir -p` it.
   - Copy parent JSONL → `<encoded-target-cwd>/<uuid>.jsonl`. **This is the load-bearing step**: `claude --resume <uuid>` resolves against the cwd of the launching subprocess, not the orchestrator's cwd. The JSONL must be in the target cwd's project dir.
   - Build the wrapped prompt (mandate + agent identity + scope + mailbox protocol + done/abort criteria + invoke-karpathy first action).
   - `subprocess.Popen([claude, --resume, uuid, --model, m, --dangerously-skip-permissions, -p, prompt], cwd=worktree, stdout=log.out, stderr=log.err, stdin=DEVNULL, start_new_session=True)`. The `start_new_session=True` detaches the child from this script's process group so it survives after spawn-parallel exits — that's what makes fire-and-poll work.
   - Write the PID to `logs/<task-name>.pid`.
4. **Mailbox setup.** Creates `mailbox/<task-name>/{inbox,seen,outbox}/` for each agent and `mailbox/orchestrator/{inbox,seen,outbox}/` for the brokering hub.
5. **Manifest.** Writes `.tmp/parallel-orchestrate/<tag>/manifest.json` listing every fork's UUID, target cwd, branch, PID, log paths, and JSONL path. Both `--status` and `--cleanup` read this.

## Cleanup

`--cleanup --session-tag <tag>` reads the manifest and reverses each step:

- Sends SIGTERM to each PID still alive, waits 0.5s, then SIGKILL if still up.
- Removes the forked JSONL files.
- With `--remove-worktrees`: `git worktree remove --force <path>` for each.
- With `--purge-session-dir`: `rm -rf` the `.tmp/parallel-orchestrate/<tag>/` dir entirely (loses reports + mailbox + manifest).

Reports + mailbox stay by default — the orchestrator may still need them for reconcile.

## Status

`--status --session-tag <tag>` prints a one-line-per-agent snapshot: PID, alive y/n, report landed y/n, inbox depth (unread messages), branch name. Also shows the orchestrator's own inbox depth. Cheap; safe to run on a /loop.

## Why permissions are `--dangerously-skip-permissions`

Forks are non-interactive — they're background `claude -p` subprocesses with no terminal. Earlier prototypes used `--permission-mode acceptEdits`, but that still prompts for `Bash`, network fetches, and `git commit`. Those prompts fire into a stdout file no human is watching, and the agent silently stalls.

`--dangerously-skip-permissions` removes ALL approval prompts so the agent runs end-to-end without intervention. Acceptable in `worktree` mode because each fork's edits are isolated to a sibling working tree branched from a known substrate, and the orchestrator inspects every commit at reconcile before merging. In `shared` mode the blast radius is wider — only use shared mode when you've verified the per-agent file scopes don't overlap.

If you want stricter permissions, edit the `cmd` list in `spawn_one()` — but understand that the "set it and forget it" property of fire-and-poll evaporates the moment any tool prompts a stdout file with no reader.

## Relationship to cc-fork

`cc-fork` (STRML/cc-skills) does the same JSONL snapshot, but:

- Blocks until all forks complete (thread-joins them) — incompatible with fire-and-poll
- Captures each fork's stdout as a returned string — fine for a quick fanout, useless for long-running feature work where the orchestrator wants to poll status mid-flight
- Doesn't do worktrees or branches — every fork shares the orchestrator's cwd

We borrow cc-fork's JSONL-copy trick verbatim. We replace the threaded `subprocess.run(... -p ...)` with detached `Popen(... -p ..., start_new_session=True)` so each agent outlives this script. The wrapper layers worktree+branch+mailbox on top.

If you have cc-fork installed, it's still the right tool for short, headless, "give me N parallel opinions" tasks. spawn-parallel is the right tool for feature-scoped, branch-per-agent, "give me N concurrent feature implementations" tasks.

## Common failures and fixes

**`--parent <uuid>: no such JSONL at …`.** The UUID isn't a session in this cwd's project dir. List candidates: `ls -lt ~/.claude/projects/<encoded-cwd>/*.jsonl | head -5`.

**`session not found` in an agent's stderr log.** The JSONL didn't land in the right project dir. Check that `~/.claude/projects/<encoded-worktree-path>/<uuid>.jsonl` exists. The encoding replaces every non-alphanumeric with `-`. Worktree `/Users/x/repo-worktrees/payments` → project dir `-Users-x-repo-worktrees-payments`.

**`branch 'feature/<name>' already exists`.** Leftover from an aborted run, or you used the same task name twice. Either `git branch -D feature/<name>` or rename the task.

**`worktree already exists at …`.** Same root cause. Run `--cleanup --remove-worktrees --session-tag <old-tag>`, or pick a new task name.

**Agent PID is gone but no report.** Tail `logs/<agent>.err`. Common causes: model rate-limit (visible in stderr), JSONL not in target project dir (`session not found`), prompt mis-parsed (shell-quoting issue if you've customized the wrapper).

**Forks don't see parent context.** Verify the parent JSONL was actually copied:
```bash
ls -la ~/.claude/projects/<encoded-target-cwd>/
```
If empty, your encoding doesn't match Claude Code's. Compare:
```bash
python3 -c "import re; from pathlib import Path; print(re.sub(r'[^a-zA-Z0-9]', '-', str(Path('<your-target>').resolve())))"
```

**Agent ignores its inbox.** The wrapper prompt instructs `ls inbox/` between steps, but the model may forget on long runs. Either tighten the wrapper (in `build_agent_prompt`) or send a "check your inbox now" message — the wrapper tells the agent to read its own inbox too, so the message will be picked up next poll.

## Extending

- **Different branch prefix.** Use `--branch-prefix feat` or `--branch-prefix ""` (no prefix). Already supported.
- **Different model per agent.** Already supported via `name:model:prompt` task format.
- **Different cwd per agent (non-worktree).** Add a `--target-cwd` per task and a third (or fourth) colon segment to `parse_task`. The JSONL copy logic already handles arbitrary cwds.
- **Blocking mode.** If you want spawn-parallel to wait for all reports before returning, add a `--wait-for-reports` flag that polls `reports/*.md` count and returns once it matches `len(tasks)`. The current fire-and-poll design assumes the orchestrator does this polling itself.
- **Auto-broker.** A small daemon could watch `mailbox/orchestrator/inbox/` and forward obvious peer-to-peer messages without the orchestrator brokering manually. Add as a `--broker-daemon` background loop if message volume gets high.

## `--watch` mode (event stream)

`cmd_watch()` runs a polling loop (default 2 s) that emits one structured stdout
line per state transition. Output is line-buffered (`flush=True`) so the
orchestrator's `Monitor` tool can deliver each line as a notification.

### State carried in-memory (lost on restart by design)

| Variable | Type | Purpose |
|----------|------|---------|
| `seen_reports` | `set[str]` | Agent names already REPORT-emitted; prevents duplicates |
| `seen_msgs` | `set[str]` | Inbox filenames already MSG-emitted |
| `dead_emitted` | `set[str]` | Agent names already DEAD-flagged |
| `silent_emitted` | `dict[str, float]` | Agent → log mtime at the moment of flagging; if mtime advances past that value, the flag clears so a fresh stall can re-fire |
| `alive_prev` | `dict[str, bool]` | Per-agent alive state from the previous iteration, used to detect alive→dead transitions |

### Startup behaviour

1. Emits `WATCH_START` with manifest path and agent count.
2. Snapshot replay: scans `reports/` and `mailbox/orchestrator/inbox/` once;
   emits `REPORT` / `MSG` for everything currently present. Makes Ctrl+C →
   re-attach transparent.
3. Enters poll loop.

### Shutdown behaviour

- `ALL_DONE` (all expected reports landed AND no alive PIDs) → emit terminal
  event, exit 0. The orchestrator's `Monitor` returns; Phase 6 begins.
- SIGTERM / SIGINT → exit 0 silently. Agents keep running. Re-attach with the
  same `--watch` command and snapshot replay covers any state that landed while
  the watcher was detached.

### Known limitations

- **No exit code in DEAD events.** Agents are launched detached, so the watcher
  observes them only via PID liveness, not as child processes. DEAD payload uses
  `exit=?` and relies on the `last_err_tail` (last 5 lines of `.err`) for
  diagnosis. If exit code is essential for future workflows, switch to a
  pidfd-based wait — but that needs Linux-only code paths and complicates the
  cross-platform story.
- **Zombie-process detection on macOS.** `os.kill(pid, 0)` succeeds for zombie
  (defunct) processes until they're reaped, which would make alive→dead
  transitions undetectable. `is_process_alive()` therefore also runs
  `ps -p <pid> -o state=` and treats state `Z` as dead. Linux behaves the same
  way; the `ps` fallback is portable.
- **Filesystem polling, not fsevents/kqueue.** At the small file counts involved
  (≤ ~10 agents × small inbox), `glob + stat` at 2 s intervals is cheap enough.
  Switching to native fs-watching would add OS-specific code without measurable
  benefit.

### Environment variable

- `PO_TMP_ROOT` — if set, the watcher resolves the session dir under this root
  instead of `os.getcwd()`. Used exclusively by the test suite at
  `parallel-orchestrate/tests/test_watch.py`. Production callers should not set
  this. Note: `cmd_status()` and `cmd_cleanup()` currently still resolve their
  session dir from `os.getcwd()` directly (not via the helper) — they don't
  honour `PO_TMP_ROOT`. This is a pre-existing pattern, not in scope here.
