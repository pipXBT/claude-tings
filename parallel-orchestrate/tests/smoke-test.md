# Smoke test — Monitor delivers watcher events in real orchestrator session

**Date:** 2026-05-16
**Skill commit:** 8623755 (autonomy-compliance) + this smoke-test commit

## Scope

The unit tests in `test_watch.py` exercise the watcher script in isolation. They
prove the script *produces* the right stdout lines. They do NOT prove that the
orchestrator's `Monitor` tool *delivers* those lines to the orchestrator session
as notifications. That's the end-to-end integration we still need to verify.

This smoke test exercises the integration without needing a full real fanout
(which would require a real target project and 30-90 min of agent work).

## Setup — hand-crafted session dir

```bash
SMOKE_ROOT=/tmp/po-smoke-49877
mkdir -p "$SMOKE_ROOT/.tmp/parallel-orchestrate/smoke1/"{reports,logs,mailbox/orchestrator/inbox,mailbox/orchestrator/seen,mailbox/demo-agent/{inbox,seen,outbox}}
printf '{"session_tag":"smoke1","spawns":[{"task_name":"demo-agent","pid":99999,"branch":"feature/demo-agent","worktree":"/tmp/fake","jsonl":"/tmp/fake.jsonl","model":"sonnet"}]}\n' \
  > "$SMOKE_ROOT/.tmp/parallel-orchestrate/smoke1/manifest.json"
printf "all done\n" > "$SMOKE_ROOT/.tmp/parallel-orchestrate/smoke1/reports/demo-agent.md"
touch "$SMOKE_ROOT/.tmp/parallel-orchestrate/smoke1/logs/demo-agent.out"
touch "$SMOKE_ROOT/.tmp/parallel-orchestrate/smoke1/logs/demo-agent.err"
```

The manifest declares 1 agent (`demo-agent`) with a fake PID that won't be alive.
A `reports/demo-agent.md` is pre-placed. So the watcher should:
1. Emit `WATCH_START` with `agents=1`
2. Snapshot-replay the existing report → emit `REPORT demo-agent`
3. See `reports == 1/1` and `alive == 0` → emit `ALL_DONE reports=1/1 alive=0`
4. `sys.exit(0)`

## Step 1 — direct invocation (baseline)

```bash
PO_TMP_ROOT=$SMOKE_ROOT python3 \
  /Users/shawnhopkinson/PipXBT_Repo/claude-tings/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag smoke1 --watch --poll-sec 0.2
```

Output (verbatim):
```
[2026-05-16T10:22:19Z] WATCH_START manifest=/tmp/po-smoke-49877/.tmp/parallel-orchestrate/smoke1/manifest.json agents=1
[2026-05-16T10:22:19Z] REPORT demo-agent /tmp/po-smoke-49877/.tmp/parallel-orchestrate/smoke1/reports/demo-agent.md
[2026-05-16T10:22:19Z] ALL_DONE reports=1/1 alive=0
```

Exit code 0. **PASS** — the script behaves correctly against a session dir
produced by hand using the same schema `cmd_spawn` writes.

## Step 2 — Monitor delivery (the integration test)

Invoked from the orchestrator session via the `Monitor` tool:

```
Monitor({
  description: "parallel-orchestrate smoke1 watcher",
  command: "PO_TMP_ROOT=/tmp/po-smoke-49877 python3 /Users/shawnhopkinson/PipXBT_Repo/claude-tings/parallel-orchestrate/scripts/spawn-parallel.py --session-tag smoke1 --watch --poll-sec 0.2",
  persistent: false,
  timeout_ms: 5000
})
```

Notification received (verbatim from the task-notification system message):

```
[2026-05-16T10:22:23Z] WATCH_START manifest=/tmp/po-smoke-49877/.tmp/parallel-orchestrate/smoke1/manifest.json agents=1
[2026-05-16T10:22:23Z] REPORT demo-agent /tmp/po-smoke-49877/.tmp/parallel-orchestrate/smoke1/reports/demo-agent.md
[2026-05-16T10:22:23Z] ALL_DONE reports=1/1 alive=0
```

Followed by: `Monitor "parallel-orchestrate smoke1 watcher" stream ended`.

**Observations:**

- All 3 events arrived as expected — content matches the direct-invocation
  baseline exactly.
- All 3 lines were batched into a single notification (consistent with the
  Monitor schema's "stdout lines within 200ms are batched into a single
  notification" rule — the watcher emits all three in <0.3 s).
- The stream-end notification arrived as a separate signal, giving the
  orchestrator a clean handoff to Phase 6.

**PASS** — Monitor delivers watcher events to the orchestrator session as
notifications, and `ALL_DONE` → script exit cleanly terminates the stream.

## What this smoke test does NOT cover

- A real fanout with `cmd_spawn` creating real agent subprocesses. Requires a
  target project and 30-90 min of agent work; deferred to first real use.
- `persistent: true` invocation against a long-running fanout. Tested only with
  `persistent: false` and a 5 s timeout here. The schema and documented
  Monitor behaviour should make `persistent: true` straightforward but it has
  not been smoke-tested in this commit.
- Re-attach (Ctrl+C → second `--watch` call → snapshot replay). Covered by
  unit-test `test_sigterm_exits_clean_with_agents_alive` for the clean-exit
  half; full re-attach loop deferred.
- DEAD / SILENT events in a Monitor delivery context. Both KINDs are covered
  by unit tests but the smoke test only exercised WATCH_START / REPORT /
  ALL_DONE. The delivery mechanism is identical so it should work, but it's
  not directly verified here.

## Verdict

**Implementation is ready to use in a real fanout.** The riskiest design
assumption — that `Monitor` will reliably deliver structured stdout lines as
notifications and surface the command's exit to the orchestrator — is verified
in this real orchestrator session. Defer the full real-world fanout to the
first practical opportunity; if it surfaces issues, log them as follow-ups.
