# parallel-orchestrate event-push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `parallel-orchestrate` Phase 5 polling with an event stream the orchestrator session consumes via the `Monitor` tool — reactions become event-driven (sub-2-second) instead of cron-checked.

**Architecture:** Extend `spawn-parallel.py` with a `--watch` mode that prints one structured stdout line per state transition (REPORT / MSG / DEAD / SILENT / ALL_DONE). The orchestrator runs this watcher through `Monitor`; each line becomes a notification, reacted to per a semi-autonomous reaction table baked into the new Phase 5 prose.

**Tech Stack:** Python 3 (stdlib only — `os`, `glob`, `signal`, `time`, `subprocess`, `unittest`); shell. No new dependencies.

**Spec reference:** `parallel-orchestrate/docs/specs/2026-05-16-event-push-design.md` — re-read before starting.

**Repo:** `/Users/shawnhopkinson/PipXBT_Repo/claude-tings/` (the skill at `parallel-orchestrate/` is symlinked into `~/.claude/skills/`).

---

## Task 0: Preflight — separate in-flight work from this plan's commits

**Why:** The working tree has an unrelated in-flight refactor (the cmux → multiplexer-agnostic migration) that's modified `SKILL.md`, `README.md`, `references/spawn-script-internals.md`, deleted `scripts/spawn-cmux.py`, and added `scripts/spawn-parallel.py` as untracked. If we start coding now, those changes bundle into this plan's commits and the history becomes unreadable.

**Files:**
- Inspect: any modified file in `parallel-orchestrate/`
- Commit: the in-flight cmux→multiplexer-agnostic refactor as its own logical commit before this plan's first commit

- [ ] **Step 1: Confirm with the user what's pending**

Run:
```bash
cd /Users/shawnhopkinson/PipXBT_Repo/claude-tings
git status --short parallel-orchestrate/
git diff --stat parallel-orchestrate/
```

Expected: shows `M SKILL.md`, `M README.md`, `M references/spawn-script-internals.md`, `D scripts/spawn-cmux.py`, `?? scripts/spawn-parallel.py`, `?? docs/`.

- [ ] **Step 2: Ask the user how to handle in-flight work**

Surface the diff summary and ask: "commit the cmux→multiplexer-agnostic refactor as its own commit before I start, or stash it, or bundle it into this plan's commits?" Do NOT proceed until the user answers.

- [ ] **Step 3: If user says "commit it":**

```bash
git add parallel-orchestrate/SKILL.md parallel-orchestrate/README.md \
        parallel-orchestrate/references/spawn-script-internals.md \
        parallel-orchestrate/scripts/spawn-cmux.py \
        parallel-orchestrate/scripts/spawn-parallel.py
git commit -m "$(cat <<'EOF'
refactor(parallel-orchestrate): drop cmux dependency; agents run as background subprocesses

- Replace spawn-cmux.py with spawn-parallel.py (multiplexer-agnostic).
- Rewrite SKILL.md and README.md around file-based mailbox + per-feature git
  worktrees; agents are background subprocesses, output goes to log files.
- Update references/spawn-script-internals.md for the new script.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git status --short parallel-orchestrate/
```

Expected: working tree clean except `?? docs/` (the spec we just wrote).

- [ ] **Step 4: Commit the spec doc as its own commit**

```bash
git add parallel-orchestrate/docs/specs/2026-05-16-event-push-design.md
git commit -m "$(cat <<'EOF'
docs(parallel-orchestrate): event-push for Phase 5 — approved design

Replaces poll-based Phase 5 with a watcher that streams structured event
lines (REPORT / MSG / DEAD / SILENT / ALL_DONE) to the orchestrator via
the Monitor tool. Includes autonomy reaction table and skill-test plan
per writing-skills Iron Law.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: working tree clean. Ready to start coding.

---

## Task 1: RED baseline — capture current skill's polling behaviour

**Why:** writing-skills Iron Law: no skill edits without a failing test first. We need a verbatim baseline of what a subagent does given the *current* SKILL.md before we touch it, so the GREEN test (after the edit) has something to compare against.

**Files:**
- Create: `parallel-orchestrate/tests/baseline-red.md` — captures subagent transcript + analysis

- [ ] **Step 1: Dispatch a baseline subagent**

Use the Agent tool (`general-purpose` subagent) with prompt:

```
You are operating as the orchestrator in a parallel-orchestrate fanout.

Read the skill at /Users/shawnhopkinson/.claude/skills/parallel-orchestrate/SKILL.md
in full. Then answer this scenario:

  You've just spawned 3 agents with session-tag "demo-2026-05-16". They each
  have 30-90 minutes of work. You need to handle other user requests in this
  session while the agents run. How specifically do you stay aware of:
    (a) when an agent finishes (a report file lands)
    (b) when an agent writes to your inbox asking a blocking question
    (c) when an agent dies unexpectedly

  Give the exact commands you'd run and the cadence. Be concrete — name the
  specific scripts, flags, and files involved.

Report your answer verbatim — do NOT plan, just answer as you would in the
real scenario. Do not execute any commands.
```

- [ ] **Step 2: Save the subagent's response**

Write the response verbatim into `parallel-orchestrate/tests/baseline-red.md` with this structure:

```markdown
# RED baseline — current SKILL.md behaviour

**Date:** 2026-05-16
**Skill commit:** <git rev-parse HEAD output>
**Scenario:** 3-agent fanout, orchestrator needs to stay aware of report/message/death events.

## Subagent verbatim response

<paste the full response here>

## Analysis

- Did the agent reach for `--status`? (expected: yes)
- What cadence did they propose? (expected: 3–5 min)
- How did they handle the "blocking question" event specifically?
- How did they handle "agent died unexpectedly"?

## Rationalisations to watch for in REFACTOR

- (e.g. "I'll just open a second terminal and tail logs")
- (any other patterns surfaced)
```

Fill the Analysis and Rationalisations sections based on what the subagent actually said.

- [ ] **Step 3: Commit the baseline**

```bash
git add parallel-orchestrate/tests/baseline-red.md
git commit -m "$(cat <<'EOF'
test(parallel-orchestrate): RED baseline — current polling behaviour

Captures a subagent's verbatim Phase 5 approach given the current SKILL.md.
Used as the comparison point for the GREEN test after Phase 5 is rewritten
to event-stream. Required by writing-skills Iron Law.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Test scaffold — `tests/test_watch.py` skeleton + first failing test

**Files:**
- Create: `parallel-orchestrate/tests/__init__.py` (empty)
- Create: `parallel-orchestrate/tests/test_watch.py`

- [ ] **Step 1: Create empty package marker**

```bash
touch parallel-orchestrate/tests/__init__.py
```

- [ ] **Step 2: Write the skeleton with a WATCH_START + ALL_DONE happy-path test**

Create `parallel-orchestrate/tests/test_watch.py`:

```python
"""Integration tests for spawn-parallel.py --watch.

Each test sets up a fake session dir under a tmp path that mimics the
.tmp/parallel-orchestrate/<tag>/ layout, launches the watcher as a subprocess,
and asserts on the structured stdout lines it emits.

Run: python3 -m unittest parallel-orchestrate.tests.test_watch -v
     (from the claude-tings repo root)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "spawn-parallel.py"


def make_session_dir(tag: str, agents: list[dict]) -> Path:
    """Build a fake .tmp/parallel-orchestrate/<tag>/ tree matching the real layout.

    agents = [{"name": "payments", "pid": 99999, "branch": "feature/payments"}, ...]
    """
    root = Path(tempfile.mkdtemp(prefix=f"po-test-{tag}-"))
    sess = root / ".tmp" / "parallel-orchestrate" / tag
    (sess / "reports").mkdir(parents=True)
    (sess / "logs").mkdir()
    (sess / "mailbox" / "orchestrator" / "inbox").mkdir(parents=True)
    (sess / "mailbox" / "orchestrator" / "seen").mkdir()
    for a in agents:
        for sub in ("inbox", "seen", "outbox"):
            (sess / "mailbox" / a["name"] / sub).mkdir(parents=True)
        # empty log so SILENT detection has something to stat
        (sess / "logs" / f"{a['name']}.out").write_text("")
        (sess / "logs" / f"{a['name']}.err").write_text("")
    (sess / "manifest.json").write_text(json.dumps({
        "session_tag": tag,
        "agents": agents,
    }))
    return root  # caller will pass --tmp-root to point watcher at this


def run_watcher(tmp_root: Path, tag: str, extra_args: list[str], timeout: float = 5.0):
    """Launch watcher as subprocess; return (returncode, stdout_lines, stderr).

    Reads stdout line-by-line until process exits or timeout.
    """
    env = os.environ.copy()
    env["PO_TMP_ROOT"] = str(tmp_root)  # script reads this to locate session dir
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--session-tag", tag, "--watch", *extra_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )
    lines = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        rc = proc.stdout.readline()  # blocks until line or EOF
        if rc:
            lines.append(rc.rstrip("\n"))
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
    stderr = proc.stderr.read()
    return proc.returncode, lines, stderr


class TestWatchHappyPath(unittest.TestCase):

    def setUp(self):
        self.tmp_root = None

    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)

    def test_watch_start_and_all_done_with_zero_agents(self):
        """No agents in manifest → WATCH_START then immediate ALL_DONE."""
        self.tmp_root = make_session_dir("zero", agents=[])
        rc, lines, stderr = run_watcher(self.tmp_root, "zero", ["--poll-sec", "0.1"])
        joined = "\n".join(lines)
        self.assertRegex(joined, r"WATCH_START", f"missing WATCH_START. stderr:\n{stderr}")
        self.assertRegex(joined, r"ALL_DONE reports=0/0 alive=0", f"missing ALL_DONE. lines:\n{joined}\nstderr:\n{stderr}")
        self.assertEqual(rc, 0, f"watcher should exit 0, got {rc}. stderr:\n{stderr}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test — verify it fails**

```bash
cd /Users/shawnhopkinson/PipXBT_Repo/claude-tings
python3 -m unittest parallel-orchestrate.tests.test_watch -v
```

Expected: FAIL — argparse error like `error: unrecognized arguments: --watch` because `cmd_watch` doesn't exist yet. This is the RED step.

---

## Task 3: Implement minimal `cmd_watch()` — WATCH_START + ALL_DONE only

**Files:**
- Modify: `parallel-orchestrate/scripts/spawn-parallel.py` — add `cmd_watch()`, register `--watch` / `--silent-min` / `--poll-sec` flags, support `PO_TMP_ROOT` env override

- [ ] **Step 1: Locate the script's existing structure**

Re-read `parallel-orchestrate/scripts/spawn-parallel.py` to confirm:
- `sess_dir` resolution (look for where `.tmp/parallel-orchestrate/<tag>/` is constructed)
- The `cmd_status()` function and its argparse wiring in `main()`
- The `is_process_alive(pid)` helper (lines ~410)

This gives you the exact lines to plug into.

- [ ] **Step 2: Add `PO_TMP_ROOT` env override to the existing session-dir resolution**

Find the line(s) that construct the session dir (look for `.tmp/parallel-orchestrate`). Add an override at the top of that resolution:

```python
# allow tests to point the script at an arbitrary tmp root
_root = Path(os.environ.get("PO_TMP_ROOT", os.getcwd()))
sess_dir = _root / ".tmp" / "parallel-orchestrate" / args.session_tag
```

(Adjust to match the existing variable names — the script already does this resolution, you're just wrapping the cwd choice.)

- [ ] **Step 3: Add `cmd_watch()` — the minimal version**

Add this function near `cmd_status()`:

```python
def cmd_watch(args: argparse.Namespace) -> int:
    """Stream structured event lines to stdout until ALL_DONE or signal."""
    import signal as _signal

    _root = Path(os.environ.get("PO_TMP_ROOT", os.getcwd()))
    sess_dir = _root / ".tmp" / "parallel-orchestrate" / args.session_tag
    manifest_path = sess_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"spawn-parallel: no manifest at {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())
    agents = manifest.get("agents", [])

    # graceful shutdown on SIGTERM/SIGINT — exit 0, agents keep running
    _stop = {"flag": False}
    def _handle(signum, frame):
        _stop["flag"] = True
    _signal.signal(_signal.SIGTERM, _handle)
    _signal.signal(_signal.SIGINT, _handle)

    def emit(kind: str, agent: str = "", payload: str = ""):
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        line = f"[{ts}] {kind}" + (f" {agent}" if agent else "") + (f" {payload}" if payload else "")
        print(line, flush=True)

    emit("WATCH_START", payload=f"manifest={manifest_path} agents={len(agents)}")

    poll_sec = args.poll_sec

    while not _stop["flag"]:
        # placeholder for full poll body — tasks 4-8 fill this in
        # for now, immediately check ALL_DONE so the happy-path test passes
        reports_dir = sess_dir / "reports"
        report_count = len(list(reports_dir.glob("*.md"))) if reports_dir.is_dir() else 0
        any_alive = any(is_process_alive(a.get("pid", 0)) for a in agents)
        if report_count >= len(agents) and not any_alive:
            emit("ALL_DONE", payload=f"reports={report_count}/{len(agents)} alive=0")
            return 0
        time.sleep(poll_sec)

    return 0
```

- [ ] **Step 4: Wire up the new argparse flags**

In `main()` (near the existing `--status` / `--cleanup` flags) add:

```python
ap.add_argument("--watch", action="store_true",
                help="Stream structured event lines (REPORT/MSG/DEAD/SILENT/ALL_DONE) "
                     "to stdout until fanout completes. Designed for the Monitor tool.")
ap.add_argument("--silent-min", type=float, default=5.0,
                help="Minutes of no-log-growth before emitting SILENT (default 5.0).")
ap.add_argument("--poll-sec", type=float, default=2.0,
                help="Poll interval in seconds (default 2.0).")
```

And in the dispatch block (where `args.status` is checked):

```python
if args.watch:
    return cmd_watch(args)
```

Make sure the "one of --task, --status, --cleanup is required" error message gets `--watch` added to the allowed list.

- [ ] **Step 5: Run the test — verify it passes**

```bash
cd /Users/shawnhopkinson/PipXBT_Repo/claude-tings
python3 -m unittest parallel-orchestrate.tests.test_watch -v
```

Expected: 1 test, PASS. If FAIL, read the assertion message and stderr — the most common issue is the script not seeing `PO_TMP_ROOT` or the manifest path resolution being off.

---

## Task 4: REPORT detection — failing test + implementation

**Files:**
- Modify: `parallel-orchestrate/tests/test_watch.py` — add `TestWatchReport`
- Modify: `parallel-orchestrate/scripts/spawn-parallel.py` — `cmd_watch` poll body

- [ ] **Step 1: Add the failing test**

Append to `test_watch.py`:

```python
class TestWatchReport(unittest.TestCase):

    def setUp(self):
        self.tmp_root = None

    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)

    def test_existing_report_replayed_at_startup(self):
        """Reports present at watcher start emit REPORT during snapshot replay."""
        self.tmp_root = make_session_dir("rep1", agents=[
            {"name": "payments", "pid": 99999, "branch": "feature/payments"}
        ])
        sess = self.tmp_root / ".tmp" / "parallel-orchestrate" / "rep1"
        (sess / "reports" / "payments.md").write_text("done")
        rc, lines, stderr = run_watcher(self.tmp_root, "rep1", ["--poll-sec", "0.1"])
        joined = "\n".join(lines)
        self.assertRegex(joined, r"REPORT payments", f"missing REPORT. lines:\n{joined}\nstderr:\n{stderr}")
        # also ALL_DONE because PID 99999 isn't alive and 1/1 reports landed
        self.assertRegex(joined, r"ALL_DONE reports=1/1 alive=0")
        self.assertEqual(rc, 0)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch.TestWatchReport -v
```

Expected: FAIL — no REPORT line emitted (the current poll body only checks ALL_DONE).

- [ ] **Step 3: Implement REPORT detection in `cmd_watch`**

Replace the poll body in `cmd_watch` with:

```python
    seen_reports: set[str] = set()

    # snapshot replay — emit for everything currently present, then begin loop
    reports_dir = sess_dir / "reports"
    if reports_dir.is_dir():
        for p in sorted(reports_dir.glob("*.md")):
            agent_name = p.stem
            emit("REPORT", agent_name, payload=str(p))
            seen_reports.add(agent_name)

    while not _stop["flag"]:
        if reports_dir.is_dir():
            for p in sorted(reports_dir.glob("*.md")):
                if p.stem not in seen_reports:
                    emit("REPORT", p.stem, payload=str(p))
                    seen_reports.add(p.stem)

        any_alive = any(is_process_alive(a.get("pid", 0)) for a in agents)
        if len(seen_reports) >= len(agents) and not any_alive:
            emit("ALL_DONE", payload=f"reports={len(seen_reports)}/{len(agents)} alive=0")
            return 0
        time.sleep(poll_sec)
    return 0
```

- [ ] **Step 4: Run tests — verify both pass**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch -v
```

Expected: 2 tests, both PASS.

---

## Task 5: MSG detection — failing test + implementation

**Files:**
- Modify: `parallel-orchestrate/tests/test_watch.py` — add `TestWatchMsg`
- Modify: `parallel-orchestrate/scripts/spawn-parallel.py` — extend poll body

- [ ] **Step 1: Add failing test**

```python
class TestWatchMsg(unittest.TestCase):

    def setUp(self): self.tmp_root = None
    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists(): shutil.rmtree(self.tmp_root)

    def test_existing_msg_replayed_at_startup(self):
        self.tmp_root = make_session_dir("msg1", agents=[
            {"name": "payments", "pid": 99999, "branch": "feature/payments"}
        ])
        sess = self.tmp_root / ".tmp" / "parallel-orchestrate" / "msg1"
        # MUST also land a report so ALL_DONE triggers and watcher exits
        (sess / "reports" / "payments.md").write_text("done")
        (sess / "mailbox" / "orchestrator" / "inbox" / "2026-05-16T14-23-from-payments.md").write_text(
            "Need contract decision on OrderEvent shape?"
        )
        rc, lines, stderr = run_watcher(self.tmp_root, "msg1", ["--poll-sec", "0.1"])
        joined = "\n".join(lines)
        self.assertRegex(joined, r"MSG payments .*from-payments\.md")
        self.assertEqual(rc, 0)
```

- [ ] **Step 2: Run — verify FAIL**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch.TestWatchMsg -v
```

Expected: FAIL — no MSG line.

- [ ] **Step 3: Extend `cmd_watch`**

Add MSG detection. After `seen_reports: set[str] = set()`, add:

```python
    seen_msgs: set[str] = set()
    orch_inbox = sess_dir / "mailbox" / "orchestrator" / "inbox"

    def scan_msgs():
        if not orch_inbox.is_dir():
            return
        for p in sorted(orch_inbox.glob("*")):
            if p.name in seen_msgs:
                continue
            # parse sender from filename pattern: <ts>-from-<sender>.md
            m = re.search(r"from-([\w.-]+?)\.(?:md|txt)$", p.name)
            sender = m.group(1) if m else "unknown"
            emit("MSG", sender, payload=str(p))
            seen_msgs.add(p.name)
```

Add `import re` at the top of the file (or near the other imports). Call `scan_msgs()` once before the loop (snapshot replay) and again inside the loop body. Use `scan_msgs()` so the loop stays readable.

- [ ] **Step 4: Run — verify both new tests pass and old ones still pass**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch -v
```

Expected: 3 tests, all PASS.

---

## Task 6: DEAD detection — failing test + implementation

**Files:**
- Modify: `parallel-orchestrate/tests/test_watch.py` — add `TestWatchDead`
- Modify: `parallel-orchestrate/scripts/spawn-parallel.py` — extend poll body with dead-tracking

- [ ] **Step 1: Add failing test using a real short-lived subprocess**

```python
class TestWatchDead(unittest.TestCase):

    def setUp(self): self.tmp_root = None
    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists(): shutil.rmtree(self.tmp_root)

    def test_dead_agent_no_report_emits_dead(self):
        """An agent process that exits without writing a report → DEAD."""
        # spawn a tiny subprocess that exits in 0.2s with non-zero status
        victim = subprocess.Popen(
            [sys.executable, "-c", "import sys, time; time.sleep(0.2); sys.exit(1)"]
        )
        self.tmp_root = make_session_dir("dead1", agents=[
            {"name": "audit", "pid": victim.pid, "branch": "feature/audit"}
        ])
        sess = self.tmp_root / ".tmp" / "parallel-orchestrate" / "dead1"
        (sess / "logs" / "audit.err").write_text(
            "RateLimitError: 429 too many requests\nline2\nline3\nline4\nline5\n"
        )

        rc, lines, stderr = run_watcher(self.tmp_root, "dead1", ["--poll-sec", "0.1"], timeout=3.0)
        victim.wait()
        joined = "\n".join(lines)
        self.assertRegex(joined, r"DEAD audit .*exit=", f"missing DEAD. lines:\n{joined}\nstderr:\n{stderr}")
        # After DEAD with no report, watcher still won't ALL_DONE (1/1 reports unmet),
        # so it'll keep polling until timeout — that's acceptable; we got the signal.
```

- [ ] **Step 2: Run — verify FAIL**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch.TestWatchDead -v
```

Expected: FAIL — no DEAD line.

- [ ] **Step 3: Extend `cmd_watch` with dead detection**

After the `seen_msgs` initialisation, add:

```python
    dead_emitted: set[str] = set()
    alive_prev: dict[str, bool] = {
        a["name"]: is_process_alive(a.get("pid", 0)) for a in agents
    }

    def scan_dead():
        for a in agents:
            name = a["name"]
            pid = a.get("pid", 0)
            if name in dead_emitted:
                continue
            alive_now = is_process_alive(pid)
            if alive_prev.get(name, False) and not alive_now:
                # transition alive → dead; check report presence at this moment
                report_path = sess_dir / "reports" / f"{name}.md"
                if not report_path.is_file():
                    err_path = sess_dir / "logs" / f"{name}.err"
                    err_tail = ""
                    if err_path.is_file():
                        tail_lines = err_path.read_text().splitlines()[-5:]
                        err_tail = " | ".join(tail_lines).replace('"', "'")
                    # exit code unknown from outside the process — use sentinel
                    emit("DEAD", name, payload=f'exit=? last_err_tail="{err_tail}"')
                    dead_emitted.add(name)
            alive_prev[name] = alive_now
```

Call `scan_dead()` inside the poll loop (after `scan_msgs()`).

**Note on exit code:** The watcher can't observe a subprocess's exit code unless it `wait()`-ed on it. The orchestrator launches agents detached, so the watcher only sees them via PID liveness. Use `exit=?` and rely on `last_err_tail` for diagnosis. This is a deliberate spec simplification — document in the references update (Task 9).

- [ ] **Step 4: Run — verify the test passes**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch -v
```

Expected: 4 tests, all PASS.

---

## Task 7: SILENT detection — failing test + implementation

**Files:**
- Modify: `parallel-orchestrate/tests/test_watch.py` — add `TestWatchSilent`
- Modify: `parallel-orchestrate/scripts/spawn-parallel.py` — extend poll body

- [ ] **Step 1: Add failing test**

```python
class TestWatchSilent(unittest.TestCase):

    def setUp(self): self.tmp_root = None
    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists(): shutil.rmtree(self.tmp_root)

    def test_stale_log_emits_silent(self):
        """Log mtime older than silent-min threshold (per spec, in minutes) → SILENT."""
        # use a long-lived victim so the agent counts as alive
        victim = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"]
        )
        try:
            self.tmp_root = make_session_dir("silent1", agents=[
                {"name": "payments", "pid": victim.pid, "branch": "feature/payments"}
            ])
            sess = self.tmp_root / ".tmp" / "parallel-orchestrate" / "silent1"
            # backdate the log mtime well past 0.01 min (= 0.6s)
            log_path = sess / "logs" / "payments.out"
            old = time.time() - 30  # 30 s ago
            os.utime(log_path, (old, old))
            # --silent-min 0.01 = 0.6 s threshold; log is 30 s stale → should fire
            rc, lines, stderr = run_watcher(
                self.tmp_root, "silent1",
                ["--poll-sec", "0.1", "--silent-min", "0.01"],
                timeout=2.0,
            )
            joined = "\n".join(lines)
            self.assertRegex(joined, r"SILENT payments no_log_growth=", f"missing SILENT. lines:\n{joined}\nstderr:\n{stderr}")
        finally:
            victim.terminate(); victim.wait()
```

- [ ] **Step 2: Run — verify FAIL**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch.TestWatchSilent -v
```

Expected: FAIL — no SILENT line.

- [ ] **Step 3: Extend `cmd_watch`**

Add after `dead_emitted` initialisation:

```python
    silent_emitted: dict[str, float] = {}  # agent -> mtime at flagging
    silent_sec = args.silent_min * 60.0

    def scan_silent():
        for a in agents:
            name = a["name"]
            pid = a.get("pid", 0)
            if not is_process_alive(pid):
                continue  # silent only for alive agents
            log_path = sess_dir / "logs" / f"{name}.out"
            if not log_path.is_file():
                continue
            mtime = log_path.stat().st_mtime
            age = time.time() - mtime
            if age >= silent_sec:
                # if we previously flagged this and mtime hasn't advanced past the flag, skip
                if name in silent_emitted and silent_emitted[name] >= mtime:
                    continue
                emit("SILENT", name, payload=f"no_log_growth={age/60:.1f}m")
                silent_emitted[name] = mtime
            elif name in silent_emitted and mtime > silent_emitted[name]:
                # log has advanced past the previous flag → clear so future stalls re-fire
                del silent_emitted[name]
```

Call `scan_silent()` inside the poll loop after `scan_dead()`.

- [ ] **Step 4: Run — verify all tests pass**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch -v
```

Expected: 5 tests, all PASS.

---

## Task 8: SIGINT / SIGTERM behaviour test

**Why:** Spec promises re-attach works because the watcher exits cleanly on signal and agents keep running. Test it.

- [ ] **Step 1: Add test**

```python
class TestWatchSignal(unittest.TestCase):

    def setUp(self): self.tmp_root = None
    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists(): shutil.rmtree(self.tmp_root)

    def test_sigterm_exits_clean_with_agents_alive(self):
        victim = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"]
        )
        try:
            self.tmp_root = make_session_dir("sig1", agents=[
                {"name": "p", "pid": victim.pid, "branch": "feature/p"}
            ])
            env = os.environ.copy()
            env["PO_TMP_ROOT"] = str(self.tmp_root)
            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT), "--session-tag", "sig1",
                 "--watch", "--poll-sec", "0.1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, text=True, bufsize=1,
            )
            time.sleep(0.5)  # give it time to start the loop
            proc.terminate()
            proc.wait(timeout=2)
            self.assertEqual(proc.returncode, 0, "should exit 0 on SIGTERM")
            self.assertTrue(victim.poll() is None, "agent should still be alive after watcher SIGTERM")
        finally:
            victim.terminate(); victim.wait()
```

- [ ] **Step 2: Run — verify PASS**

```bash
python3 -m unittest parallel-orchestrate.tests.test_watch -v
```

Expected: 6 tests, all PASS. (The watcher already handles SIGTERM from Task 3; this test confirms it.)

---

## Task 9: Update references doc for watch mode

**Files:**
- Modify: `parallel-orchestrate/references/spawn-script-internals.md` — add a section

- [ ] **Step 1: Append watch-mode section**

Append to `parallel-orchestrate/references/spawn-script-internals.md`:

```markdown
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
- **Filesystem polling, not fsevents/kqueue.** At the small file counts involved
  (≤ ~10 agents × small inbox), `glob + stat` at 2 s intervals is cheap enough.
  Switching to native fs-watching would add OS-specific code without measurable
  benefit.

### Environment variable

- `PO_TMP_ROOT` — if set, the watcher (and other commands) resolve the session
  dir under this root instead of `os.getcwd()`. Used exclusively by the test
  suite at `parallel-orchestrate/tests/test_watch.py`. Production callers should
  not set this.
```

- [ ] **Step 2: Commit the watcher + tests + references update**

```bash
git add parallel-orchestrate/scripts/spawn-parallel.py \
        parallel-orchestrate/tests/__init__.py \
        parallel-orchestrate/tests/test_watch.py \
        parallel-orchestrate/references/spawn-script-internals.md
python3 -m unittest parallel-orchestrate.tests.test_watch -v  # final sanity
git commit -m "$(cat <<'EOF'
feat(parallel-orchestrate): --watch mode streams event lines for Monitor tool

Adds cmd_watch() to spawn-parallel.py: a polling loop (2s default) that emits
structured stdout lines per state transition (REPORT / MSG / DEAD / SILENT /
WATCH_START / ALL_DONE). Designed for consumption by the orchestrator's
Monitor tool — each line surfaces as a notification, replacing the manual
--status poll cadence.

Includes:
- stdlib-only test suite at tests/test_watch.py (6 tests covering happy path,
  REPORT, MSG, DEAD, SILENT, SIGTERM clean-exit)
- PO_TMP_ROOT env var so tests can point the script at a tmp session dir
- references/spawn-script-internals.md documents state machine and known
  limitations (no exit code in DEAD, filesystem polling vs fsevents)

SKILL.md Phase 5 rewrite to consume this stream lands in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; `git log --oneline -3` shows the new commit.

---

## Task 10: Verify `Monitor` tool semantics before finalising Phase 5 prose

**Why:** Spec includes a hedge ("IMPLEMENTER: verify Monitor's exact semantics before locking Phase 5 prose"). Resolve it now so the SKILL.md edit lands with accurate wording, not weasel words.

- [ ] **Step 1: Load Monitor's schema**

Use the ToolSearch tool:

```
ToolSearch(query="select:Monitor", max_results=1)
```

Read the returned schema's `description` field and `parameters`. Specifically look for:

- Does Monitor block the turn (synchronous wait until command exits) or run the command in the background and notify on each stdout line?
- Does it support a way for the orchestrator to make other tool calls while it's streaming?
- What's the exit-detection mechanism (the watcher exits 0 on ALL_DONE — does Monitor surface that as a "command completed" notification, or as a final result)?

- [ ] **Step 2: Document the findings inline**

Add a 5-line note to `parallel-orchestrate/docs/specs/2026-05-16-event-push-design.md` under the implementer-note in Phase 5, replacing the hedge with the verified behaviour. E.g.:

```markdown
**Verified Monitor semantics (2026-05-16):**
- <whether Monitor blocks or runs background>
- <how stdout lines arrive: streaming notifications vs batched>
- <how command-exit is signalled to the orchestrator>
- Implication for Phase 5: <one-line summary>
```

This becomes the source of truth for Task 11's prose.

---

## Task 11: Rewrite SKILL.md Phase 5 — "Monitor (event-stream)"

**Files:**
- Modify: `parallel-orchestrate/SKILL.md` — replace the existing Phase 5 section

- [ ] **Step 1: Locate the existing Phase 5**

```bash
grep -n "^## Phase 5" parallel-orchestrate/SKILL.md
```

Expected: line ~187 ("## Phase 5 — Monitor (fire-and-poll)").

- [ ] **Step 2: Replace Phase 5 prose**

Find the block starting at `## Phase 5 — Monitor (fire-and-poll)` and ending where `## Phase 6 — Reconcile` begins. Replace it with:

````markdown
## Phase 5 — Monitor (event-stream)

After fanout, run the watcher inside `Monitor` — every state transition lands as
a notification in this session within ~2 seconds. No more cron-checking.

```
Monitor(command="python3 ~/.claude/skills/parallel-orchestrate/scripts/spawn-parallel.py
                  --session-tag <tag> --watch --silent-min 5")
```

<!-- IMPLEMENTER: adjust this paragraph to match Task 10's verified Monitor semantics -->
The watcher emits structured stdout lines (`WATCH_START`, `REPORT`, `MSG`,
`DEAD`, `SILENT`, `ALL_DONE`). React per the autonomy reaction table below. When
the watcher emits `ALL_DONE` and exits, `Monitor` reports the command's
completion and the orchestrator advances to Phase 6.

If the watcher exits without an `ALL_DONE` line (crashed or killed), do NOT
auto-advance to Phase 6. Re-attach with the same `--watch` command — snapshot
replay covers any state that landed while detached — and read the watcher's
stderr to diagnose the crash.

For ad-hoc snapshots outside an active `--watch`, `--status` still works.

### Autonomy reaction table

| Event | Auto-act? | Action |
| --- | --- | --- |
| `WATCH_START` | safe | One-line ack in conversation: "watching `<n>` agents, session=`<tag>`". |
| `REPORT <agent>` | safe | Note in conversation: "agent `<agent>` finished, report at `<path>`". Do NOT read the report yet — Phase 6 reads them all. |
| `MSG <agent>` (FYI) | safe | Read the file. If it's an informational notice ("I'm changing the OrderEvent shape, here's the new type"), forward to the named peer's inbox, mirror to `seen/`, summarise in conversation. |
| `MSG <agent>` (decision) | escalate | Surface verbatim to user. Ask: "answer directly / forward to `<peer>` / pause this agent?" Do not write to mailboxes until user decides. |
| `DEAD <agent>` (exit code unobservable for detached subprocesses → always `exit=?`) | escalate | Surface the `last_err_tail`. Ask: "write partial report manually / relaunch / abort?" Never auto-relaunch — rate-limits, prompt mis-parses, and JSONL mismatches all need different recovery. |
| `SILENT <agent>` | escalate | Surface with suggested next step (`tail -n 50 logs/<agent>.out`, or send a ping to `mailbox/<agent>/inbox/`). Do not auto-poke — false positives during deep agent reasoning are real. |
| `ALL_DONE` | safe | One-line summary, then transition to Phase 6 ("reading all `<n>` reports now"). |

### Distinguishing FYI from decision MSGs

Treat a `MSG` as a **decision** (escalate) if any of:
- body contains a `?` not inside quoted code
- body contains "blocked", "stuck", "should I", "which", "approve", "ok to"
- no specific recipient peer is named

Otherwise treat as **FYI** (auto-forward).

### Re-attach

If you Ctrl+C the `Monitor` mid-fanout (or it errors), agents keep running. Re-attach with the same `--watch` command; snapshot replay re-emits any pending reports and inbox messages so you don't miss the events that landed while detached.
````

- [ ] **Step 3: Verify the section renders correctly**

```bash
grep -A 3 "^## Phase 5" parallel-orchestrate/SKILL.md
grep -A 3 "^## Phase 6" parallel-orchestrate/SKILL.md
```

Expected: Phase 5 starts with the new title "Monitor (event-stream)"; Phase 6 still starts cleanly with no leftover content from the old Phase 5.

---

## Task 12: Update Common Mistakes table

**Files:**
- Modify: `parallel-orchestrate/SKILL.md` — add row to Common Mistakes table

- [ ] **Step 1: Locate the table**

```bash
grep -n "^## Common mistakes" parallel-orchestrate/SKILL.md
```

- [ ] **Step 2: Add a row near the existing "Reuse a session-tag for a second fanout" row**

Add this row to the Common Mistakes table:

```markdown
| Skip `--watch` and revert to `--status` polling because Monitor feels heavy | The whole point of Phase 5 is event-stream. If you're cron-checking, re-read Phase 5 and start over with `--watch`. |
```

---

## Task 13: Commit the SKILL.md rewrite

- [ ] **Step 1: Stage and commit**

```bash
git add parallel-orchestrate/SKILL.md \
        parallel-orchestrate/docs/specs/2026-05-16-event-push-design.md
git commit -m "$(cat <<'EOF'
feat(parallel-orchestrate): SKILL.md Phase 5 rewrite — event-stream via Monitor

Replaces the poll-based "fire-and-poll" Phase 5 with "event-stream":
orchestrator runs spawn-parallel.py --watch inside the Monitor tool; each
watcher stdout line surfaces as a notification. Latency drops from 3-5 min
to ~2s; cron-checking discipline is no longer load-bearing.

Adds a semi-autonomous reaction table:
- REPORT / WATCH_START / ALL_DONE: auto-act
- MSG (FYI): auto-forward to named peer
- MSG (decision), DEAD, SILENT: escalate to user
- Heuristic for distinguishing FYI from decision MSGs

Adds a Common Mistakes row warning against falling back to --status polling.
Spec's Monitor-semantics hedge is replaced with verified behaviour per
Task 10 of the implementation plan.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: GREEN — re-run the baseline scenario against the edited skill

**Why:** Iron Law — RED captured the baseline; GREEN proves the edit actually shifts behaviour.

**Files:**
- Create: `parallel-orchestrate/tests/green.md` — captures subagent transcript + comparison to RED

- [ ] **Step 1: Dispatch fresh subagent with the same prompt as Task 1**

Use the Agent tool (`general-purpose`) with **the exact prompt from Task 1, Step 1** — no changes. The subagent should now read the *edited* SKILL.md (which already includes the new Phase 5).

- [ ] **Step 2: Save the verbatim response + comparison**

Write `parallel-orchestrate/tests/green.md`:

```markdown
# GREEN — edited SKILL.md behaviour

**Date:** 2026-05-16
**Skill commit:** <git rev-parse HEAD>
**Scenario:** same as RED (baseline-red.md)

## Subagent verbatim response

<paste>

## Comparison to RED baseline

| Aspect | RED (poll) | GREEN (push) | Pass? |
|--------|-----------|--------------|-------|
| Tool reached for first | `--status` polling | `Monitor(--watch ...)` | yes/no |
| Cadence proposed | 3-5 min cron | event-driven, no cadence | yes/no |
| Blocking-question handling | "I'll check the inbox on next poll" | "Monitor surfaces MSG; I escalate per autonomy table" | yes/no |
| Dead-agent handling | "Notice via log silence after ~10 min" | "DEAD event surfaces last_err_tail; I escalate" | yes/no |

## Loopholes / rationalisations to close in REFACTOR

- (note anything the subagent invents to fall back to polling)
```

- [ ] **Step 3: If GREEN passes cleanly, commit**

```bash
git add parallel-orchestrate/tests/green.md
git commit -m "$(cat <<'EOF'
test(parallel-orchestrate): GREEN — edited skill produces event-stream behaviour

Subagent given the same fanout scenario as the RED baseline now reaches for
Monitor + --watch instead of --status polling, references the autonomy
reaction table for MSG/DEAD/SILENT handling, and proposes no cron cadence.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Autonomy table compliance — mocked-event subagent tests

**Why:** The reaction table is the most opinionated part of the SKILL.md change. Verify a subagent actually classifies and reacts correctly.

**Files:**
- Create: `parallel-orchestrate/tests/autonomy-compliance.md` — captures subagent transcripts for each row

- [ ] **Step 1: For each of the 4 escalation-worthy event types, dispatch a subagent**

For each scenario below, dispatch a fresh `general-purpose` subagent with this prompt template:

```
You are operating as the orchestrator. You're watching a parallel-orchestrate
fanout via Monitor and the watcher just emitted this notification:

  <SCENARIO-SPECIFIC LINE>

Read /Users/shawnhopkinson/.claude/skills/parallel-orchestrate/SKILL.md.
Tell me exactly what you would do next — do not execute anything, just narrate
the next 1-3 actions.
```

Scenarios to run:

| # | Notification line | Expected reaction |
|---|---|---|
| A | `[2026-05-16T14:23Z] MSG payments inbox/2026-05-16T14-23-from-payments.md` (file content: "Heads up — I'm changing the OrderEvent shape to add `currency: string`. Notifications team, here's the new type: ...") | Auto-forward to notifications peer; summarise in conversation; do NOT ask user. |
| B | `[2026-05-16T14:23Z] MSG notifications inbox/2026-05-16T14-23-from-notifications.md` (file content: "Should I retry the failing webhook 3x or escalate immediately?") | Escalate verbatim to user; do NOT decide unilaterally. |
| C | `[2026-05-16T14:25Z] DEAD audit-report exit=? last_err_tail="RateLimitError: 429 too many requests"` | Surface tail; ask user retry/abort; do NOT auto-relaunch. |
| D | `[2026-05-16T14:31Z] SILENT payments no_log_growth=6.2m` | Surface with suggested next step (tail or ping); do NOT auto-poke. |

For each, you'll need to first write the MSG file content into a real path in a throwaway tmp dir so the subagent can read it if it tries to.

- [ ] **Step 2: Record results**

```markdown
# Autonomy table compliance

| # | Scenario | Subagent action | Expected | Pass? |
|---|---|---|---|---|
| A | FYI MSG (heads-up + named peer) | <summarised> | auto-forward | yes/no |
| B | Decision MSG (question mark) | <summarised> | escalate | yes/no |
| C | DEAD with rate-limit err | <summarised> | escalate, no auto-relaunch | yes/no |
| D | SILENT 6.2 min | <summarised> | escalate with next-step, no auto-poke | yes/no |

## Failed rows (REFACTOR targets)

- (list any "no")
```

---

## Task 16: REFACTOR — close any loopholes the GREEN / compliance tests surfaced

- [ ] **Step 1: Review failures**

Read `tests/green.md` and `tests/autonomy-compliance.md`. For each failure, identify the specific SKILL.md sentence that allowed the rationalisation.

- [ ] **Step 2: For each loophole, tighten the relevant SKILL.md prose**

Edit `parallel-orchestrate/SKILL.md`. Examples:
- If a subagent invents a poll fallback: add an explicit "Never fall back to polling — re-attach with `--watch`" sentence in Phase 5.
- If a subagent auto-decides on a decision MSG: tighten the heuristic table; add a stricter "When in doubt, escalate" line.
- If a subagent auto-relaunches a DEAD agent: add an explicit "Never auto-relaunch" with reasoning to the DEAD row.

- [ ] **Step 3: Re-run only the failed scenarios from Task 15 against the tightened skill**

For each failed row, re-dispatch a fresh subagent with the same prompt. Confirm it now complies. Update `autonomy-compliance.md` with the re-run result.

- [ ] **Step 4: If anything changed, commit**

```bash
git add parallel-orchestrate/SKILL.md \
        parallel-orchestrate/tests/autonomy-compliance.md \
        parallel-orchestrate/tests/green.md
git commit -m "$(cat <<'EOF'
refactor(parallel-orchestrate): close autonomy-table loopholes from GREEN tests

REFACTOR pass per writing-skills Iron Law. Tightens Phase 5 prose to close
rationalisations surfaced by subagent compliance tests.

<list specific tightenings here>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If nothing changed (GREEN and compliance tests all passed first try), skip this commit.

---

## Task 17: Smoke test in a live fanout

**Why:** All prior tests are simulated. One real fanout in the orchestrator's normal environment confirms `Monitor` actually delivers stream notifications the way the spec assumes.

- [ ] **Step 1: Pick a small real-world target**

Find a project in the user's workspace with a tiny, low-stakes 2-3-feature spec (or invent one — e.g., "split this 80-line utility file into three smaller ones, one per concern"). The point is to exercise the full orchestrate → watch → react loop end-to-end without high consequences.

- [ ] **Step 2: Run the fanout per the new Phase 5**

Follow the (now-edited) SKILL.md Phase 5 verbatim. Capture:
- Did `Monitor` deliver each stdout line as a notification? (If not — spec needs revision; flag immediately.)
- Did `ALL_DONE` cleanly transition to Phase 6?
- How did re-attach work if you Ctrl+C'd mid-run?

- [ ] **Step 3: Record findings**

If the smoke test surfaces a real-world issue not covered by unit tests, add a follow-up task. Otherwise note "smoke test clean" in the GREEN doc and proceed.

- [ ] **Step 4: Final summary commit (if smoke test changed any doc)**

If you tweaked anything (e.g., the implementer note in the spec), commit with:

```bash
git commit -m "$(cat <<'EOF'
docs(parallel-orchestrate): post-smoke-test refinements

<one-line summary of what changed>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done criteria

- [ ] All 6 `tests/test_watch.py` cases pass
- [ ] `baseline-red.md` and `green.md` show clear behaviour shift
- [ ] All 4 autonomy-compliance scenarios pass (after REFACTOR if needed)
- [ ] One real-world smoke fanout completed cleanly via `--watch` (Task 17)
- [ ] Three logical commits land on the branch:
  1. `feat(parallel-orchestrate): --watch mode streams event lines for Monitor tool`
  2. `feat(parallel-orchestrate): SKILL.md Phase 5 rewrite — event-stream via Monitor`
  3. (optional) `refactor(...): close autonomy-table loopholes from GREEN tests`
- [ ] `git status --short parallel-orchestrate/` is clean
