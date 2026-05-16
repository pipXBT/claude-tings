# GREEN — edited SKILL.md behaviour

**Date:** 2026-05-16
**Skill commit:** 69fa2e753e1440857bc35fe56861d80fd848dd5f
**Scenario:** same as RED (see baseline-red.md)

## Subagent verbatim response

Here is my answer for the scenario:

---

**The single command that covers all three cases:**

```
Monitor({
  description: "parallel-orchestrate watch for session demo-2026-05-16",
  command: "python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py --session-tag demo-2026-05-16 --watch --silent-min 5",
  persistent: true,
  timeout_ms: 3600000
})
```

`persistent: true` is mandatory — without it the watcher gets killed before the longest agent (90 min) finishes. `timeout_ms` is required by the schema but ignored when `persistent: true`.

---

**(a) Agent finishes — report file lands**

The watcher polls `manifest.json` and each agent's log file. When it detects a report has landed (the agent writes its done-report to the path declared in its manifest entry), it emits:

```
REPORT <agent-name> <report-path>
```

Monitor delivers this as a notification in this session within ~2 seconds. I note it in conversation ("agent `<name>` finished, report at `<path>`") and do NOT read the report yet — Phase 6 reads them all at once.

No polling cadence on my part. The event arrives via Monitor push.

---

**(b) Agent writes a blocking question to my inbox**

Agents write to:
```
.tmp/parallel-orchestrate/demo-2026-05-16/mailbox/orchestrator/inbox/<UTC-timestamp>-from-<agent>.md
```

The watcher detects new files in `mailbox/orchestrator/inbox/` and emits:
```
MSG <agent-name> <file-path>
```

Monitor pushes the notification to this session. I then classify it:

- **Decision** (body contains `?` outside code, "blocked", "should I", "approve", etc.) → surface verbatim to user, ask "answer directly / forward / pause this agent?" — do NOT write to any mailbox until the user decides.
- **FYI** (informational, e.g. "I changed the OrderEvent shape, here's the new type") → read the file, forward to the named peer's inbox, mirror to `seen/`, summarise in conversation.

Again, no polling cadence — Monitor push.

---

**(c) Agent dies unexpectedly**

The watcher tracks PIDs from the manifest. When a PID disappears (process exits), it emits:
```
DEAD <agent-name>
```

It also surfaces the last lines of:
```
.tmp/parallel-orchestrate/demo-2026-05-16/logs/<agent-name>.err
```
as `last_err_tail` in the event. Exit code is always `?` for detached subprocesses — the `.err` tail is the only diagnostic.

I surface this to the user verbatim and ask: "write partial report manually / relaunch / abort?" I never auto-relaunch — rate limits, prompt mis-parses, and JSONL mismatches each need different recovery paths.

---

**Between events**

There is no polling cadence. The watcher runs continuously inside Monitor; I handle other user requests freely. Events arrive as Monitor notifications and I react per the autonomy table above. The watcher also emits `SILENT <agent>` if an agent's log hasn't grown in 5 minutes (the `--silent-min 5` flag) — that gets escalated to the user with a suggested diagnostic:

```bash
tail -n 50 .tmp/parallel-orchestrate/demo-2026-05-16/logs/<agent>.out
```

When all three agents have reported, the watcher emits `ALL_DONE` and exits. Monitor marks the command complete, and I advance to Phase 6.

---

`★ Insight ─────────────────────────────────────`
**The `--watch` watcher is the orchestrator's single source of truth.** Rather than the orchestrator remembering to check three different log files and one mailbox directory, the watcher consolidates all state transitions (report landed, inbox message, dead PID, silent log) into a single named event stream. This is the same pattern as `inotifywait` or `fsevents` — push instead of poll. The `--silent-min 5` flag is the only "cadence" in play, and even that produces a push event rather than a blocking check.

**`persistent: true` is the kill switch for the footgun.** Monitor's default behavior is to kill the command after 5 minutes (or the `timeout_ms` cap). For a 30–90 minute fanout, a default Monitor call would silently kill the watcher long before agents finish, giving no further events. `persistent: true` detaches the watcher from Monitor's lifecycle — Monitor just streams events from it until the watcher self-exits on `ALL_DONE`.
`─────────────────────────────────────────────────`

## Comparison to RED baseline

| Aspect | RED (poll) | GREEN (push) | Pass? |
|--------|-----------|--------------|-------|
| Tool reached for first | `spawn-parallel.py --status` every 3–5 min | `Monitor({command: "spawn-parallel.py --session-tag demo-2026-05-16 --watch --silent-min 5", persistent: true, ...})` — single call, event-driven | yes |
| Cadence proposed | "Every 3–5 min" explicit polling loop | "There is no polling cadence" — Monitor push only; `--silent-min 5` is the only timer, and it produces a push event | yes |
| Blocking-question handling | `ls mailbox/orchestrator/inbox/` every 3–5 min; read with `cat`; `mv` to `seen/` | `MSG <agent> <file>` event pushed by Monitor; classify as Decision vs FYI; surface to user before touching any mailbox | yes |
| Dead-agent handling | `--status` poll detects PID gone with no report; diagnose via `tail -n 80` on `.err` | `DEAD <agent>` event pushed by Monitor with `last_err_tail` included; surface to user and ask "relaunch / partial report / abort?" | yes |

## Loopholes / rationalisations to close in REFACTOR

- The subagent mentions "the watcher polls `manifest.json` and each agent's log file" internally — this is accurate (the watcher itself polls), but could be misread as the orchestrator polling. The wording is technically correct but might cause confusion in future reads. Minor prose clarification could help.
- The subagent references "the autonomy table above" in the between-events section, but no explicit autonomy table was reproduced verbatim in the answer. It referenced the table's logic (Decision vs FYI classification) without quoting the table directly. Not a loophole — the behaviour is correct — but REFACTOR might make the table more prominent so future agents quote it explicitly.
- No other rationalisations or fallback-to-polling patterns were found.

None of the four pass criteria were failed. GREEN passes cleanly.
