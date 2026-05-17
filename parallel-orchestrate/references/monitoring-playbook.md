# Monitoring playbook

Detailed reactions to every `--watch` event, the SILENT false-positive cross-check, the FYI-vs-decision MSG rule, and the relaunch procedure for a dead agent. SKILL.md Phase 5 gives the quick path; load this when an event needs more than the one-line summary.

## Autonomy reaction table

| Event | Auto-act? | Action |
| --- | --- | --- |
| `WATCH_START` | safe | One-line ack in conversation: "watching `<n>` agents, session=`<tag>`". |
| `REPORT <agent>` | safe | Note in conversation: "agent `<agent>` finished, report at `<path>`". Do NOT read the report yet — Phase 6 reads them all. |
| `MSG <agent>` (FYI) | safe | Read the file. If it's an informational notice ("I'm changing the OrderEvent shape, here's the new type"), forward to the named peer's inbox, mirror to `seen/`, summarise in conversation. |
| `MSG <agent>` (decision) | escalate | Surface verbatim to user. Ask: "answer directly / forward to `<peer>` / pause this agent?" Do not write to mailboxes until user decides. |
| `DEAD <agent>` | escalate | Surface the `last_err_tail` (exit code is always `?` because agents are detached subprocesses — the `.err` tail is the diagnostic). Ask: "write partial report manually / relaunch / abort?" Never auto-relaunch — rate-limits, prompt mis-parses, and JSONL mismatches each need different recovery. |
| `SILENT <agent>` | escalate | Cross-check before surfacing — see "SILENT false-positive pattern" below. Surface to user only if all three cross-checks show no activity. Do NOT auto-poke. |
| `ALL_DONE` | safe | One-line summary, then transition to Phase 6 ("reading all `<n>` reports now"). |

## SILENT false-positive pattern

The `claude` CLI block-buffers stdout when redirected to a non-TTY file (libc default for non-interactive streams, ~4KB+ before flush). An agent actively editing files via Edit/Write can produce no log growth for `silent_min` minutes while making real progress in the worktree — watcher emits SILENT, agent is fine. The cross-check `git -C <worktree> status --porcelain` returning any `M`/`??` lines is deterministic proof the agent is working; the log silence is a buffering artefact, not a stall.

Three-step cross-check that eliminates 100% of observed false positives:

1. `ps -p <pid>` — process alive
2. `git -C <worktree> status --porcelain` — uncommitted changes present (`M`/`??`)
3. `ls <session-dir>/reports/` — no premature report

If 1 + 2 are positive, ignore the SILENT and continue waiting. The watcher's `scan_silent()` already does this cross-check at source, so the event won't even emit when uncommitted changes exist — the orchestrator-side cross-check remains as a fallback for older watcher versions.

A clean wrapper fix (e.g., `stdbuf -oL claude ...`) isn't available: macOS doesn't ship `stdbuf` by default, and `claude` is a Mach-O native binary (not Node), so libc-layer buffering hints may not apply. Cross-check is the recommended pattern.

## Distinguishing FYI from decision MSGs

Treat a `MSG` as a **decision** (escalate) if any of:

- body contains a `?` not inside quoted code
- body contains "blocked", "stuck", "should I", "which", "approve", "ok to"
- no specific recipient peer is named

Otherwise treat as **FYI** (auto-forward). **When in doubt, escalate** — over-asking is cheap; auto-deciding a contract question that should have been yours is expensive.

## Re-attach

If you Ctrl+C the `Monitor` mid-fanout (or it errors), agents keep running. Re-attach with the same `--watch` command; snapshot replay re-emits any pending reports and inbox messages so you don't miss the events that landed while detached.

## After a relaunch: ALL_DONE may fire spuriously

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

## Relaunching a dead agent

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
