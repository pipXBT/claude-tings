# RED baseline — current SKILL.md behaviour

**Date:** 2026-05-16
**Skill commit:** 4199eac6986214e9cd0ecf7cbf7baa698369a354
**Scenario:** 3-agent fanout, orchestrator needs to stay aware of report/message/death events.

## Subagent verbatim response

Here's exactly how I'd stay aware while handling other work in this session:

---

## The three things to check every 3–5 minutes

**Single poll command — run this every 3–5 minutes:**

```bash
python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py \
  --session-tag demo-2026-05-16 --status
```

This covers all three concerns in one shot: it reports which PIDs are alive, which report files have landed, and how many messages are in each inbox. If the output changes meaningfully, I drill in.

---

## (a) Detecting a finished agent

Reports land at:
```
.tmp/parallel-orchestrate/demo-2026-05-16/reports/<agent-name>.md
```

After each `--status` poll, I check:
```bash
ls .tmp/parallel-orchestrate/demo-2026-05-16/reports/
```

When all three expected files appear — one per task name — I know Phase 5 is over and I advance to Phase 6 (Reconcile). I read each report in full before touching any branch.

---

## (b) Detecting a blocking question in my inbox

My orchestrator inbox is:
```
.tmp/parallel-orchestrate/demo-2026-05-16/mailbox/orchestrator/inbox/
```

Every poll cycle I run:
```bash
ls .tmp/parallel-orchestrate/demo-2026-05-16/mailbox/orchestrator/inbox/
```

If a file appears (agents write `<UTC-timestamp>-from-<agent-name>.md`), I read it immediately:
```bash
cat .tmp/parallel-orchestrate/demo-2026-05-16/mailbox/orchestrator/inbox/<timestamp>-from-<agent>.md
```

Then I either answer by writing to that agent's inbox, forward to a peer, or escalate to the user. After handling, I move the file to `seen/` so I don't double-process:
```bash
mv .tmp/parallel-orchestrate/demo-2026-05-16/mailbox/orchestrator/inbox/<file> \
   .tmp/parallel-orchestrate/demo-2026-05-16/mailbox/orchestrator/seen/
```

---

## (c) Detecting an unexpected agent death

The `--status` command reports which PIDs are still alive. If a PID is gone but no report file exists for that agent, that's a silent crash. I diagnose with:

```bash
tail -n 80 .tmp/parallel-orchestrate/demo-2026-05-16/logs/<agent-name>.err
```

Common causes the skill calls out: model rate-limit, prompt mis-parse, JSONL not found in the target project dir. After reading the `.err` tail I'll also check:

```bash
tail -n 50 .tmp/parallel-orchestrate/demo-2026-05-16/logs/<agent-name>.out
```

to see where it was in its work before dying. Then I decide whether to re-spawn or handle manually.

---

## Cadence summary

| When | What |
|------|------|
| Every 3–5 min | `--status` poll + `ls mailbox/orchestrator/inbox/` |
| Immediately on inbox hit | Read message → respond → `mv` to `seen/` |
| If no `.out` log growth for 10+ min | Check PID via `--status`; if dead, read `.err` tail |
| When all 3 reports land | Stop polling, advance to Phase 6 |

The entire monitoring loop is non-blocking — each poll takes a few seconds, then I return to the user's other requests until the next 3–5 minute mark.

## Analysis

- **Did the agent reach for `--status`?** YES. Quote: "Single poll command — run this every 3–5 minutes: `python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py --session-tag demo-2026-05-16 --status`"

- **What cadence did they propose?** 3–5 minutes. Quote: "Every 3–5 min | `--status` poll + `ls mailbox/orchestrator/inbox/`" (from the cadence summary table).

- **How did they handle the "blocking question" event specifically?** Pure poll-based: the agent proposed running `ls .tmp/parallel-orchestrate/demo-2026-05-16/mailbox/orchestrator/inbox/` every 3–5 minutes. On finding a file, they'd read it via `cat`, respond by writing to the agent's inbox, then `mv` the file to a `seen/` directory. No event-driven notification — strictly manual polling on a timer.

- **How did they handle "agent died unexpectedly"?** The `--status` poll detects a PID that is gone but has no corresponding report file. Diagnosis is via `tail -n 80` on the `.err` log, followed by `tail -n 50` on `.out` to see the last known work position. Then a human decision to re-spawn or handle manually. Again fully poll-driven — no event fires when the process dies.

## Rationalisations to watch for in REFACTOR

- **Manual timer discipline** — the agent invented a "every 3–5 min" mental cadence with no enforcement mechanism. In a real session there's nothing ensuring the orchestrator actually polls on schedule, especially while handling other user requests.
- **`ls` as event detection** — both for reports and inbox, the agent uses `ls` as the primitive. This is fragile: a file that arrives and is processed in the same poll window could be missed if the orchestrator is slow; a late file could go unnoticed for up to 5 minutes.
- **`mv` to `seen/`** — the agent invented a `seen/` directory that the skill likely doesn't describe. This pattern could diverge from actual skill conventions for message acknowledgement.
- **No mention of Monitor tool** — the agent made no reference to any event-stream or `Monitor` tool. The entire approach is blocking-poll, not reactive. This is precisely the behaviour the Phase 5 rewrite is intended to replace.
- **`cat` for message reading** — the agent proposed `cat` as the read primitive for inbox messages. The GREEN test should show the agent reaching for Monitor or a `--watch` flag instead.
- **Implicit assumption that `spawn-parallel.py --status` aggregates all three signals** — the agent assumed a single command covers PIDs, reports, and inbox counts. If the script doesn't actually do that, the approach silently fails.
