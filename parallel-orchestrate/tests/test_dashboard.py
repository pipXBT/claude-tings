"""Unit tests for the --dashboard rendering pipeline.

Two layers:

    1. `_agent_state(sess_dir, agent, silent_sec)` is a pure function — given a
       manifest entry and the on-disk session layout, returns the structured
       state the TUI cell-renders. Easy to assert.

    2. `cmd_dashboard` is the live-loop wrapper. We exercise its `render()`
       helper once to prove it composes a rich Panel without raising; we do
       NOT spin up the Live loop because that takes over the TTY.

Run: python3 -m unittest parallel-orchestrate.tests.test_dashboard -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import importlib.util
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "spawn-parallel.py"


def _load_spawn_module():
    """Load spawn-parallel.py as a module despite the dash in its name."""
    spec = importlib.util.spec_from_file_location("spawn_parallel", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SP = _load_spawn_module()


def _make_session(tag: str, agents: list[dict], worktrees: dict[str, Path] | None = None) -> Path:
    """Build a fake session dir; optionally create real git worktrees per agent."""
    root = Path(tempfile.mkdtemp(prefix=f"po-dash-{tag}-"))
    sess = root / ".tmp" / "parallel-orchestrate" / tag
    (sess / "reports").mkdir(parents=True)
    (sess / "logs").mkdir()
    (sess / "mailbox" / "orchestrator" / "inbox").mkdir(parents=True)
    (sess / "mailbox" / "orchestrator" / "seen").mkdir()
    for a in agents:
        name = a["task_name"]
        for sub in ("inbox", "seen", "outbox"):
            (sess / "mailbox" / name / sub).mkdir(parents=True)
        (sess / "logs" / f"{name}.out").write_text("")
        (sess / "logs" / f"{name}.err").write_text("")
        pid_path = sess / "logs" / f"{name}.pid"
        pid_path.write_text(str(a.get("pid", 0)))
        a.setdefault("pid_file", str(pid_path))
        if worktrees and name in worktrees:
            a["cwd"] = str(worktrees[name])
    (sess / "manifest.json").write_text(json.dumps({"session_tag": tag, "spawns": agents}))
    return root


def _init_git_worktree(path: Path, dirty: bool) -> Path:
    """Create a tiny git repo at `path`. If dirty, leave an uncommitted file."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "seed.txt").write_text("seed")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)
    if dirty:
        (path / "wip.txt").write_text("agent's in-progress edit")
    return path


class TestAgentStatePureFunction(unittest.TestCase):
    """The state-determination logic the TUI table renders."""

    def setUp(self):
        self.tmp_root: Path | None = None

    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists():
            shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _sess(self, tag: str) -> Path:
        return self.tmp_root / ".tmp" / "parallel-orchestrate" / tag

    def test_alive_no_report_is_running(self):
        # use this very test process's PID — guaranteed alive during the test
        agent = {"task_name": "payments", "pid": os.getpid(), "branch": "feature/payments"}
        self.tmp_root = _make_session("a", [agent])
        s = SP._agent_state(self._sess("a"), agent, silent_sec=600)
        self.assertEqual(s["state"], "RUN")
        self.assertTrue(s["alive"])
        self.assertFalse(s["has_report"])

    def test_dead_pid_no_report_is_dead(self):
        # PID 1 (launchd on macOS) is alive; pick something that won't be ours.
        # Spawn a child and wait for it to exit so we have a definitively-dead PID.
        victim = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
        victim.wait()
        agent = {"task_name": "audit", "pid": victim.pid, "branch": "feature/audit"}
        self.tmp_root = _make_session("d", [agent])
        s = SP._agent_state(self._sess("d"), agent, silent_sec=600)
        self.assertEqual(s["state"], "DEAD")
        self.assertFalse(s["alive"])

    def test_has_report_dead_is_report(self):
        victim = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
        victim.wait()
        agent = {"task_name": "notify", "pid": victim.pid, "branch": "feature/notify"}
        self.tmp_root = _make_session("r", [agent])
        (self._sess("r") / "reports" / "notify.md").write_text("done")
        s = SP._agent_state(self._sess("r"), agent, silent_sec=600)
        self.assertEqual(s["state"], "REPORT")
        self.assertTrue(s["has_report"])

    def test_silent_with_clean_worktree(self):
        # alive + stale log + worktree has nothing uncommitted → SILENT (true positive)
        agent = {"task_name": "types", "pid": os.getpid(), "branch": "feature/types"}
        self.tmp_root = _make_session("s1", [agent])
        wt = self.tmp_root / "wt-types"
        _init_git_worktree(wt, dirty=False)
        agent["cwd"] = str(wt)
        # backdate log to 10s ago; silent_sec=1 → stale
        old = time.time() - 10
        os.utime(self._sess("s1") / "logs" / "types.out", (old, old))
        s = SP._agent_state(self._sess("s1"), agent, silent_sec=1)
        self.assertEqual(s["state"], "SILENT")

    def test_silent_cross_check_disproves_false_positive(self):
        # alive + stale log + worktree has uncommitted edits → still RUN (block-buffer artefact)
        agent = {"task_name": "platform", "pid": os.getpid(), "branch": "feature/platform"}
        self.tmp_root = _make_session("s2", [agent])
        wt = self.tmp_root / "wt-platform"
        _init_git_worktree(wt, dirty=True)
        agent["cwd"] = str(wt)
        old = time.time() - 10
        os.utime(self._sess("s2") / "logs" / "platform.out", (old, old))
        s = SP._agent_state(self._sess("s2"), agent, silent_sec=1)
        self.assertEqual(s["state"], "RUN", "cross-check should disprove SILENT")
        # and the M/?? counters should reflect the in-progress edit
        self.assertGreaterEqual(s["untracked"], 1)

    def test_inbox_count_reflects_files(self):
        agent = {"task_name": "p", "pid": os.getpid(), "branch": "feature/p"}
        self.tmp_root = _make_session("i", [agent])
        inbox = self._sess("i") / "mailbox" / "p" / "inbox"
        (inbox / "2026-05-16T01-from-orchestrator.md").write_text("hi")
        (inbox / "2026-05-16T02-from-orchestrator.md").write_text("hi")
        s = SP._agent_state(self._sess("i"), agent, silent_sec=600)
        self.assertEqual(s["inbox_count"], 2)


class TestDashboardRenderSmoke(unittest.TestCase):
    """Prove cmd_dashboard's render() helper composes without raising."""

    def setUp(self):
        self.tmp_root: Path | None = None

    def tearDown(self):
        if self.tmp_root and self.tmp_root.exists():
            shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_build_render_panel(self):
        # Two agents — one alive (this proc), one dead — exercises both styles.
        victim = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
        victim.wait()
        agents = [
            {"task_name": "a", "pid": os.getpid(),  "model": "sonnet", "branch": "feature/a"},
            {"task_name": "b", "pid": victim.pid,    "model": "opus",  "branch": "feature/b"},
        ]
        self.tmp_root = _make_session("rend", agents)
        sess = self.tmp_root / ".tmp" / "parallel-orchestrate" / "rend"
        manifest = json.loads((sess / "manifest.json").read_text())

        panel = SP._build_dashboard_panel(
            sess_dir=sess,
            manifest=manifest,
            silent_sec=600,
            session_tag="rend",
            started_at=time.time() - 90,
        )
        # rendering to a string proves the rich tree resolves without raising
        from rich.console import Console
        buf_console = Console(record=True, width=120)
        buf_console.print(panel)
        out = buf_console.export_text()
        self.assertIn("rend", out)
        self.assertIn("a", out)
        self.assertIn("b", out)


if __name__ == "__main__":
    unittest.main()
