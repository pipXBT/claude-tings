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
import select
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
            # drain any remaining output
            for remaining in proc.stdout:
                lines.append(remaining.rstrip("\n"))
            break
        remaining_sec = max(0.05, deadline - time.monotonic())
        ready, _, _ = select.select([proc.stdout], [], [], remaining_sec)
        if ready:
            line = proc.stdout.readline()
            if line:
                lines.append(line.rstrip("\n"))
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


class TestWatchDead(unittest.TestCase):

    def setUp(self): self.tmp_root = None
    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists(): shutil.rmtree(self.tmp_root)

    def test_dead_agent_no_report_emits_dead(self):
        """An agent process that exits without writing a report → DEAD."""
        # spawn a tiny subprocess that exits in 0.2s with non-zero status
        victim = subprocess.Popen(
            [sys.executable, "-c", "import sys, time; time.sleep(1.0); sys.exit(1)"]
        )
        self.tmp_root = make_session_dir("dead1", agents=[
            {"name": "audit", "pid": victim.pid, "branch": "feature/audit"}
        ])
        sess = self.tmp_root / ".tmp" / "parallel-orchestrate" / "dead1"
        (sess / "logs" / "audit.err").write_text(
            "RateLimitError: 429 too many requests\nline2\nline3\nline4\nline5\n"
        )

        rc, lines, stderr = run_watcher(self.tmp_root, "dead1", ["--poll-sec", "0.1"], timeout=4.0)
        victim.wait()
        joined = "\n".join(lines)
        self.assertRegex(joined, r"DEAD audit .*exit=", f"missing DEAD. lines:\n{joined}\nstderr:\n{stderr}")
        # After DEAD with no report, watcher still won't ALL_DONE (1/1 reports unmet),
        # so it'll keep polling until timeout — that's acceptable; we got the signal.


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


if __name__ == "__main__":
    unittest.main()
