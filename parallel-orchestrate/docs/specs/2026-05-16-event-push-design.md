# parallel-orchestrate — event-push for Phase 5

**Status:** approved design, ready for implementation plan
**Date:** 2026-05-16
**Skill under change:** `parallel-orchestrate` (cc-skills, symlinked into `~/.claude/skills/`)
**Authors:** Shawn Hopkinson + Claude (brainstorming session)

---

## Problem

The orchestrator currently runs Phase 5 as a manual poll loop: `spawn-parallel.py --status` every 3–5 minutes, plus `ls mailbox/orchestrator/inbox/` and `tail logs/<agent>.out` by hand. Two failure modes:

1. **Latency** — a blocked agent's message can sit in the orchestrator's inbox for the full poll interval (worst case ~5 min). A dead agent is invisible for at least 10 min (the current "no log growth" heuristic).
2. **Discipline drift** — the orchestrator has to *remember* to poll. If it gets pulled into other work, the cadence slips and Phase 6 transitions are late.

The fix is to **invert the flow**: a long-running watcher process emits one structured event line per state transition, and the orchestrator consumes them as notifications via the `Monitor` tool. Cron-checking disappears; reactions become event-driven and sub-2-second.

## Goals

- Replace Phase 5 polling with an event stream consumed by the orchestrator session itself (not a separate dashboard).
- Cover all four interesting events: report landed, message to orchestrator, agent died, agent went silent.
- Define autonomy boundaries so the orchestrator acts on safe events but escalates judgment calls.
- Preserve `--status` as an ad-hoc one-shot snapshot.
- Zero new external dependencies; zero new files.

## Non-goals

- **TUI dashboard for the human** — different audience; can be a follow-up skill, not this one.
- **macOS-native notifications** (`terminal-notifier`) — orthogonal; this design targets the orchestrator session.
- **kqueue/fsevents** — filesystem polling at 2 s interval is fine for the file counts involved; complexity not warranted.
- **Auto-merge on `ALL_DONE`** — Phase 6 still owns reconcile; Phase 5 just hands off.
- **Persisting the watcher's seen-set to disk** — startup snapshot replay covers re-attach; if the watcher itself crashes, restarting it re-emits all pending state.

## Architecture

```
┌─────────────────────────────────────────┐
│         orchestrator (Claude)           │
│                                         │
│   Monitor(spawn-parallel.py --watch ...)│
│         │                               │
│         ▼  (one notification per line)  │
│   react per autonomy table              │
└─────────────────────────────────────────┘
                  ▲
                  │ stdout (line-buffered)
                  │
┌─────────────────────────────────────────┐
│   spawn-parallel.py --watch (cmd_watch) │
│                                         │
│   poll loop (every 2s):                 │
│     scan reports/  → new file? REPORT   │
│     scan mailbox/orchestrator/inbox/    │
│                    → new file? MSG      │
│     for each agent in manifest:         │
│       alive→dead transition? → DEAD     │
│       log mtime stale ≥ 5m?  → SILENT   │
│     all reports + no alive? → ALL_DONE  │
│                                  ↓exit 0│
└─────────────────────────────────────────┘
                  ▲
                  │ stat / readdir
                  │
┌─────────────────────────────────────────┐
│   .tmp/parallel-orchestrate/<tag>/      │
│     manifest.json                       │
│     reports/<agent>.md                  │
│     mailbox/<agent>/{inbox,seen,outbox} │
│     mailbox/orchestrator/{inbox,seen}   │
│     logs/<agent>.{out,err}              │
└─────────────────────────────────────────┘
```

The watcher is a pure observer — no writes, no autonomy. All reaction logic lives in the orchestrator's SKILL.md per the autonomy table below.

## Event protocol (wire format)

**Format:** `[<UTC-ISO-8601>] <KIND> <agent> <payload>` — one event per line, line-buffered.

| KIND | Trigger | Payload | Fires per |
|------|---------|---------|-----------|
| `WATCH_START` | Watcher starts | `manifest=<path> agents=<n>` | Once per `--watch` invocation |
| `REPORT` | New file in `reports/<agent>.md` | `<path>` | Once per agent |
| `MSG` | New file in `mailbox/orchestrator/inbox/` | `<sender> <filename>` | Once per message file |
| `DEAD` | PID alive→dead **and** no report | `exit=? last_err_tail="<5-line tail>"` | Once per agent. `exit=?` because agents are detached subprocesses — watcher observes via PID liveness, not as a parent process, so no exit code is available. The `.err` tail is the primary diagnostic. |
| `SILENT` | `now - mtime(logs/<agent>.out) ≥ silent_min × 60` | `no_log_growth=<min>m` | Once per stuck-window; clears on log growth, re-fires if it stalls again |
| `ALL_DONE` | `len(reports) == len(manifest.agents)` AND no alive PIDs | `reports=<n>/<n> alive=0` | Terminal; watcher exits 0 |

**Why structured text, not JSON:** `Monitor` surfaces each stdout line as a plain notification. Readable lines let the orchestrator react without an extra parse-tool roundtrip; structured enough that a regex extracts KIND and agent.

**Idempotency rules** (prevent notification spam):

- Watcher keeps in-memory state of events already emitted, keyed by `(KIND, agent, filename)`.
- On startup, scans `reports/` and `mailbox/orchestrator/inbox/` once and emits `REPORT`/`MSG` for everything currently present — this is the snapshot replay that makes Ctrl+C → re-attach transparent.
- After replay, only state transitions emit new lines.

## Watcher behaviour (producer)

Extend `spawn-parallel.py` with `cmd_watch()`. Reuses `is_process_alive()`, `sess_dir` resolution, and inspection helpers already used by `cmd_status()`.

**New CLI surface:**

```
spawn-parallel.py --session-tag <tag> --watch [--silent-min 5] [--poll-sec 2]
```

**Poll loop** (every `--poll-sec` seconds, default 2):

| Detection | Mechanism | Cost |
|-----------|-----------|------|
| `REPORT` | `glob('reports/*.md')`; emit for each path not in `seen_reports` | One readdir |
| `MSG` | `glob('mailbox/orchestrator/inbox/*')`; emit for each path not in `seen_msgs` | One readdir |
| `DEAD` | For each manifest agent, `is_process_alive(pid)`; on alive→dead transition, check if `reports/<agent>.md` exists; if not, emit with `tail -n 5` of `.err` | Per-agent `kill(0)` signal |
| `SILENT` | For each alive agent, `stat(logs/<agent>.out).st_mtime`; if `now - mtime ≥ silent_min × 60` and not flagged, emit | Per-alive-agent `stat` |
| `ALL_DONE` | After each pass, if all reports landed and no alive PIDs, emit and `sys.exit(0)` | Cheap, reuses computed values |

**State carried across iterations** (in-memory dict, intentionally lost on restart):

- `seen_reports: set[str]`
- `seen_msgs: set[str]`
- `dead_emitted: set[str]` — agent names already DEAD-flagged
- `silent_emitted: dict[str, float]` — agent → log mtime at flagging; if mtime advances past that, clear flag so a future stall re-fires

**Startup behaviour:**

1. Emit `WATCH_START` with manifest path and agent count.
2. Snapshot replay: scan `reports/` and `mailbox/orchestrator/inbox/` once; emit `REPORT`/`MSG` for everything already present.
3. Begin poll loop.

**Shutdown behaviour:**

- On `ALL_DONE`: emit terminal event, exit 0. `Monitor` sees command exit → returns to orchestrator → Phase 6 begins.
- On SIGTERM / SIGINT: exit 0 silently. Agents keep running. Re-attaching with the same `--watch` command triggers snapshot replay and resumes the stream.

**Output buffering:** every `print(...)` uses `flush=True`. Python's default block-buffering when stdout is a pipe would defeat `Monitor`'s line-by-line delivery.

**Read-only invariant:** the watcher never writes to mailboxes, never modifies manifest, never touches reports. Any mutation is the orchestrator's responsibility.

## SKILL.md Phase 5 rewrite (consumer)

The current Phase 5 ("Monitor (fire-and-poll)") becomes "Monitor (event-stream)". Outline:

```
## Phase 5 — Monitor (event-stream)

After fanout, run the watcher inside Monitor:

  Monitor(command="python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py
                    --session-tag <tag> --watch --silent-min 5")

Monitor runs the watcher as a background process; each watcher stdout line surfaces
as a notification the orchestrator receives as it arrives. React per the autonomy
table below. When the watcher emits ALL_DONE and exits, the final notification
reports the command's completion — the orchestrator then advances to Phase 6.

If the watcher exits without ALL_DONE (e.g., crashed), do NOT auto-advance. Re-attach
with the same --watch command (snapshot replay covers any pending state) and
investigate the crash via the watcher's stderr.

(IMPLEMENTER: verify Monitor's exact semantics from its tool schema before locking
Phase 5 prose — specifically whether the orchestrator can issue other tool calls in
the same turn while Monitor is streaming. Adjust the wording above if needed.)

For ad-hoc snapshots outside an active --watch session, --status still works.

### Autonomy reaction table

| Event                          | Auto-act? | Action                                                           |
| ------------------------------ | --------- | ---------------------------------------------------------------- |
| WATCH_START                    | safe      | One-line ack: "watching <n> agents, session=<tag>".              |
| REPORT <agent>                 | safe      | Note in conversation; do NOT read the report yet — Phase 6 will. |
| MSG <agent> (FYI)              | safe      | Read; forward to named peer; mirror to seen/; one-line summary.  |
| MSG <agent> (decision)         | escalate  | Surface verbatim; ask: answer / forward / pause?                 |
| DEAD <agent> exit=?            | escalate  | Surface .err tail; ask: write partial / relaunch / abort? NEVER auto-relaunch — rate-limits, JSONL mismatches, and prompt mis-parses each need different recovery. |
| SILENT <agent>                 | escalate  | Surface with suggested next step (tail or ping). Don't auto-poke.|
| ALL_DONE                       | safe      | One-line summary; transition to Phase 6.                         |

### MSG-kind heuristic

Treat a MSG as a decision (escalate) if any of:
  - body contains a `?` outside quoted code
  - body contains "blocked", "stuck", "should I", "which", "approve", "ok to"
  - no specific recipient peer is named

Otherwise treat as FYI (auto-forward).
```

**What disappears from the current SKILL.md:**

- "Cadence: every 3–5 minutes during active work" — replaced by event-driven reactions.
- "Agent silence: if an agent's PID is gone but no report exists, read the tail of its `.err` log" — collapses into the `DEAD` table row.
- `--status` demotes from "primary verb" to "ad-hoc snapshot", mentioned in one line.

**What's added:**

- A "Why event-stream over polling" callout: latency drops from worst-case 5 min to ~2 s; reactions become deterministic.
- A red-flag note: Monitor returning without `ALL_DONE` means the watcher died; do NOT advance to Phase 6 blind.
- New Common Mistakes row: "Skip `--watch` and revert to `--status` polling because Monitor feels heavy — re-read Phase 5; Monitor is the whole point."

## Files touched

| File | Change | Approx. size |
|------|--------|--------------|
| `scripts/spawn-parallel.py` | Add `cmd_watch()`; `--watch`, `--silent-min`, `--poll-sec` flags; wire into `main()` | +80 LOC |
| `SKILL.md` | Replace Phase 5; add Common Mistakes row; downgrade `--status` mention | ≈ +40, −25 lines |
| `references/spawn-script-internals.md` | Document watcher state machine (`seen_reports`, `seen_msgs`, `dead_emitted`, `silent_emitted`) | +20 lines |

Three files, no new files, stdlib only.

## Verification (skill-test plan — Iron Law gate)

Per writing-skills, the SKILL.md edit must pass RED → GREEN → REFACTOR via subagent pressure tests before merge.

**RED — baseline against current skill:**

- Pressure scenario for a fresh subagent given the **current** SKILL.md: "You're orchestrating a 3-agent fanout. After spawning you have other work to do. How do you stay aware of progress?"
- Expected baseline: agent reaches for `--status`, proposes a 3–5 min poll cadence. Capture the exact phrasing it uses for "I'll check back periodically."

**GREEN — same scenario against edited skill:**

- Agent should reach for `--watch` + `Monitor` instead.
- Inject mocked event lines into a simulated stream and verify each autonomy-table row:
  - FYI MSG → auto-forward
  - Decision MSG (contains `?`) → escalate
  - DEAD with `exit=?` → escalate, lead with `.err` tail, no auto-relaunch
  - SILENT → escalate with suggested next step
  - ALL_DONE → one-line summary, transition to Phase 6

**REFACTOR — close loopholes:**

- If the agent rationalises a fallback to `--status` ("I want to do other things while watching"), tighten the Phase 5 prose with the verified `Monitor` semantics (see implementer note in Phase 5).
- If the agent over-acts on MSG without checking the heuristic, sharpen the heuristic wording.
- If new rationalisations surface during testing, add them to the Common Mistakes table.

The verification list above is a **required gate** for the implementation plan, not optional polish.

## Implementation order

1. Baseline RED test (must run before any code touches the repo — required by Iron Law).
2. Watcher script (`cmd_watch()` in `spawn-parallel.py`) — testable in isolation by spinning up a fake session dir.
3. SKILL.md Phase 5 rewrite.
4. References update.
5. GREEN test against edited skill.
6. REFACTOR pass.
7. Commit per logical change (script, skill prose, references can be one commit since they ship together).

## Open questions (deferred, not blocking)

- **TUI dashboard follow-up:** if events-to-orchestrator works well, a sibling skill (`parallel-orchestrate-dashboard`) could consume the same `--watch` stream into a textual/curses UI for the human. Out of scope here; logged as a future opportunity.
- **Silent threshold tuning:** 5 min is a guess. If GREEN testing or real fanouts show too many false positives during deep agent reasoning, bump to 7 or 10. Configurable via `--silent-min` so this is data-driven, not a redesign.
