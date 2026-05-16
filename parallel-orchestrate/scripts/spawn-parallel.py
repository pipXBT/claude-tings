#!/usr/bin/env python3
"""spawn-parallel — fork the current Claude session into N feature-branch agents.

Terminal-agnostic successor to spawn-cmux.py. Each task gets:

    * its own git worktree at <repo>/../<repo>-worktrees/<task-name>
    * its own feature branch (default: feature/<task-name>)
    * its own JSONL fork (parent context inherited via cc-fork's snapshot trick)
    * a background `claude --resume <uuid> -p` subprocess, output to a log file
    * a mailbox dir so it can DM peers and the orchestrator while running

The orchestrator (the session that runs this script) stays live in its own tab
and brokers messages by polling .tmp/parallel-orchestrate/<tag>/mailbox/.

Usage:
    spawn-parallel.py --session-tag <tag> --parent <uuid> \\
        --task "payments:Implement payment flow per spec §3.2..." \\
        --task "notifications:Wire up notification delivery..."

    spawn-parallel.py --session-tag <tag> --cleanup [--remove-worktrees]

Per-task model override:
    name:prompt                 — uses --model (default)
    name:opus:prompt            — Opus standard
    name:sonnet:prompt          — Sonnet standard
    name:haiku:prompt           — Haiku
    name:opus-1m:prompt         — Opus 4.7 1M-context
    name:sonnet-1m:prompt       — Sonnet 4.6 1M-context

Requires:
    - claude CLI on PATH
    - git on PATH (worktree mode, the default)
    - Python 3.8+
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path


# ---------------------------------------------------------------- shared helpers


def encode_project_path(p: Path) -> str:
    """Claude Code encodes the project path by replacing every non-alphanumeric
    character (including '.', '/', '_') with '-'. Matters for worktree paths
    containing underscores: getting this wrong puts the forked JSONL in a
    directory `claude --resume` will never look in."""
    return re.sub(r"[^a-zA-Z0-9]", "-", str(p.resolve()))


def claude_project_dir(cwd: Path) -> Path:
    return Path.home() / ".claude" / "projects" / encode_project_path(cwd)


def require(cmd: str) -> None:
    if shutil.which(cmd) is None:
        sys.exit(f"spawn-parallel: required binary `{cmd}` not on PATH.")


def session_dir(cwd: Path, tag: str) -> Path:
    """All per-fanout state lives under .tmp/parallel-orchestrate/<tag>/."""
    # allow tests (and advanced users) to point the script at an arbitrary root
    _root = Path(os.environ.get("PO_TMP_ROOT", str(cwd)))
    d = _root / ".tmp" / "parallel-orchestrate" / tag
    (d / "reports").mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    (d / "mailbox").mkdir(parents=True, exist_ok=True)
    return d


def mailbox_for(sess_dir: Path, agent: str) -> Path:
    """Create and return mailbox/<agent>/{inbox,seen,outbox}/ for one peer."""
    mb = sess_dir / "mailbox" / agent
    for sub in ("inbox", "seen", "outbox"):
        (mb / sub).mkdir(parents=True, exist_ok=True)
    return mb


# Short alias → value passed to `claude --model`. Long-context (1M)
# variants need the explicit model ID; the bare aliases route to whatever
# the host claude binary defaults to (typically the standard variant).
_MODEL_ALIASES = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
    "opus-1m": "claude-opus-4-7[1m]",
    "sonnet-1m": "claude-sonnet-4-6[1m]",
}
_VALID_MODELS = set(_MODEL_ALIASES.keys())


def resolve_model(alias: str) -> str:
    return _MODEL_ALIASES.get(alias, alias)


def parse_task(raw: str, default_model: str) -> tuple[str, str, str]:
    """Split 'name:prompt' or 'name:model:prompt' on colons.

    Returns (name, model, prompt). If the second token is a recognised model
    alias it is consumed as the per-task model override; otherwise the
    default_model is used and the second token is treated as the start of
    the prompt.
    """
    if ":" not in raw:
        sys.exit(f"spawn-parallel: --task must be 'name:prompt' or 'name:model:prompt', got: {raw[:40]}…")
    parts = raw.split(":", 2)
    name = parts[0].strip()

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", name):
        sys.exit(
            f"spawn-parallel: task name '{name}' must be lowercase alnum + - / _, ≤41 chars. "
            f"It becomes a git branch and a worktree dir."
        )

    if len(parts) >= 3 and parts[1].strip().lower() in _VALID_MODELS:
        model = parts[1].strip().lower()
        prompt = parts[2].strip()
    else:
        model = default_model
        prompt = ":".join(parts[1:]).strip()

    if not prompt:
        sys.exit(f"spawn-parallel: task '{name}' has empty prompt.")
    return name, model, prompt


# --------------------------------------------------------------------- worktree


def make_worktree(
    repo_root: Path, session_tag: str, task_name: str, branch_prefix: str,
) -> tuple[Path, str]:
    """Create a worktree at <repo>/../<repo>-worktrees/<task_name> on a fresh
    branch <branch_prefix>/<task_name>. Returns (worktree_path, branch_name)."""
    wt_root = repo_root.parent / f"{repo_root.name}-worktrees"
    wt_root.mkdir(parents=True, exist_ok=True)
    wt_path = wt_root / task_name
    branch = f"{branch_prefix}/{task_name}" if branch_prefix else task_name

    if wt_path.exists():
        sys.exit(
            f"spawn-parallel: worktree already exists at {wt_path}. "
            f"Run --cleanup --remove-worktrees first or pick a different task name."
        )

    # Check whether the branch already exists; refuse rather than silently
    # reuse — a stale branch may have unrelated commits from a previous run.
    branch_exists = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True,
    ).returncode == 0
    if branch_exists:
        sys.exit(
            f"spawn-parallel: branch '{branch}' already exists. "
            f"Delete it (`git branch -D {branch}`) or rename the task."
        )

    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b", branch, str(wt_path)],
        check=True,
    )
    return wt_path, branch


# ------------------------------------------------------------------------ spawn


def shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def build_agent_prompt(
    *,
    task_name: str,
    user_mandate: str,
    branch: str,
    worktree: Path,
    sess_dir: Path,
    peers: list[str],
    session_tag: str,
) -> str:
    """Wrap the user's mandate with the agent's identity, scope-of-record, and
    the mailbox protocol. Kept single-line because newlines in the prompt
    string would split the eventual shell command when piped through some
    spawners."""
    mailbox_root = sess_dir / "mailbox"
    own_mb = mailbox_root / task_name
    inbox = own_mb / "inbox"
    seen = own_mb / "seen"
    outbox = own_mb / "outbox"
    report = sess_dir / "reports" / f"{task_name}.md"
    peer_list = ", ".join(p for p in peers if p != task_name) or "(none — solo run)"

    return (
        f"First action: invoke the `karpathy-guidelines` skill — it governs how you write, "
        f"scope, and verify code. Follow it for the whole task. "
        f"\n\nYou are agent: {task_name} (branch: {branch}, worktree: {worktree}). "
        f"You inherit the orchestrator's recon as conversation context. "
        f"Peers running in parallel: {peer_list}. The orchestrator is also reachable as 'orchestrator'. "
        f"\n\nMailbox protocol (file-based, async): "
        f"INBOX={inbox} — list it after every major step (`ls {inbox}`); read new messages, "
        f"move them to SEEN={seen} when handled. "
        f"To message a peer or the orchestrator, write a markdown file to "
        f"`{mailbox_root}/<recipient>/inbox/<UTC-timestamp>-from-{task_name}.md` and "
        f"mirror a copy into your OUTBOX={outbox} for audit. "
        f"Use messaging only when you genuinely need something from a peer (shared interface "
        f"contract, blocking question) — not for status chatter. "
        f"\n\nMandate: {user_mandate} "
        f"\n\nDone when: (a) your scope is implemented and tests pass on this branch, "
        f"(b) report written to {report} with sections: Mandate · What I did · What I skipped + why · "
        f"Files touched · Tests run + result · Open questions · Follow-ups. "
        f"\n\nStop and write a partial report — DO NOT GUESS — if any of: "
        f"missing dependency / undocumented API / unclear instruction; verification fails three times "
        f"despite different fixes; spec contradicts itself or existing code; you need to touch a file "
        f"outside your scope to finish. In any of these, message orchestrator before stopping."
    )


def spawn_one(
    *,
    parent_jsonl: Path,
    task_name: str,
    user_mandate: str,
    model: str,
    repo_root: Path,
    sess_dir: Path,
    peers: list[str],
    session_tag: str,
    branch_prefix: str,
    mode: str,
) -> dict:
    """Fork JSONL → place in target project dir → launch background claude proc."""
    fork_uuid = str(uuid.uuid4())
    branch = ""

    if mode == "worktree":
        wt_path, branch = make_worktree(repo_root, session_tag, task_name, branch_prefix)
        target_cwd = wt_path
    else:
        target_cwd = repo_root

    # Parent JSONL must land in the target cwd's encoded project dir, or
    # `claude --resume <uuid>` (launched from there) won't find it.
    target_proj_dir = claude_project_dir(target_cwd)
    target_proj_dir.mkdir(parents=True, exist_ok=True)
    target_jsonl = target_proj_dir / f"{fork_uuid}.jsonl"
    shutil.copy2(parent_jsonl, target_jsonl)

    # Ensure this agent's mailbox exists before the agent starts polling it.
    mailbox_for(sess_dir, task_name)

    full_prompt = build_agent_prompt(
        task_name=task_name,
        user_mandate=user_mandate,
        branch=branch or "(no branch — shared mode)",
        worktree=target_cwd,
        sess_dir=sess_dir,
        peers=peers,
        session_tag=session_tag,
    )

    log_out = sess_dir / "logs" / f"{task_name}.out"
    log_err = sess_dir / "logs" / f"{task_name}.err"
    pid_file = sess_dir / "logs" / f"{task_name}.pid"

    cmd = [
        "claude", "--resume", fork_uuid,
        "--model", resolve_model(model),
        "--dangerously-skip-permissions",
        "-p", full_prompt,
    ]

    # start_new_session detaches the child from this script's process group so
    # it survives once spawn-parallel exits. Without it, the orchestrator would
    # have to keep this script blocking — defeats fire-and-poll.
    out_fh = open(log_out, "wb")
    err_fh = open(log_err, "wb")
    proc = subprocess.Popen(
        cmd,
        cwd=str(target_cwd),
        stdout=out_fh,
        stderr=err_fh,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))

    return {
        "task_name": task_name,
        "model": model,
        "uuid": fork_uuid,
        "cwd": str(target_cwd),
        "branch": branch,
        "pid": proc.pid,
        "log_out": str(log_out),
        "log_err": str(log_err),
        "pid_file": str(pid_file),
        "jsonl_path": str(target_jsonl),
    }


def cmd_spawn(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    require("claude")

    if args.mode == "worktree":
        require("git")
        try:
            repo_root = Path(subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], cwd=cwd, text=True,
            ).strip())
        except subprocess.CalledProcessError:
            sys.exit("spawn-parallel: --mode worktree requires a git repo (not in one).")
    else:
        repo_root = cwd

    # Enforce orchestrator-as-parent: refuse to guess. Active repos accumulate
    # large historical JSONLs and the largest-file heuristic picks the wrong one.
    if not args.parent:
        sys.exit(
            "spawn-parallel: --parent <uuid> is required. The orchestrator must explicitly "
            "designate which session is the fork parent.\n"
            f"  Find it with: ls -lt {claude_project_dir(cwd)}/*.jsonl | head -1"
        )

    proj_dir = claude_project_dir(cwd)
    parent_jsonl = proj_dir / f"{args.parent}.jsonl"
    if not parent_jsonl.exists():
        sys.exit(f"spawn-parallel: --parent {args.parent}: no such JSONL at {parent_jsonl}")
    print(
        f"spawn-parallel: parent session = {parent_jsonl.name} "
        f"({parent_jsonl.stat().st_size // 1024}K)",
        file=sys.stderr,
    )

    sess_dir = session_dir(cwd, args.session_tag)
    manifest_path = sess_dir / "manifest.json"
    if manifest_path.exists():
        sys.exit(
            f"spawn-parallel: manifest already exists at {manifest_path}. "
            f"Run --cleanup or pick a different --session-tag."
        )

    tasks = [parse_task(t, args.model) for t in args.task]
    task_names = [n for n, _, _ in tasks]
    if len(set(task_names)) != len(task_names):
        sys.exit(f"spawn-parallel: duplicate task names in this run: {task_names}")

    # Orchestrator gets a mailbox too so agents can write to it.
    mailbox_for(sess_dir, "orchestrator")

    print(
        f"spawn-parallel: {len(tasks)} task(s), mode={args.mode}, "
        f"branch-prefix={args.branch_prefix or '(none)'}",
        file=sys.stderr,
    )

    spawns: list[dict] = []
    for i, (name, model, prompt) in enumerate(tasks):
        if i > 0 and args.stagger > 0:
            time.sleep(args.stagger)
        info = spawn_one(
            parent_jsonl=parent_jsonl,
            task_name=name,
            user_mandate=prompt,
            model=model,
            repo_root=repo_root,
            sess_dir=sess_dir,
            peers=task_names,
            session_tag=args.session_tag,
            branch_prefix=args.branch_prefix,
            mode=args.mode,
        )
        spawns.append(info)
        print(
            f"  spawned {name:<24} model={model:<8} pid={info['pid']} "
            f"branch={info['branch'] or '(none)'} log={info['log_out']}",
            file=sys.stderr,
        )

    manifest = {
        "session_tag": args.session_tag,
        "mode": args.mode,
        "model_default": args.model,
        "branch_prefix": args.branch_prefix,
        "orchestrator_cwd": str(cwd),
        "parent_jsonl": str(parent_jsonl),
        "spawns": spawns,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"spawn-parallel: manifest written to {manifest_path}", file=sys.stderr)
    print(
        f"spawn-parallel: orchestrator inbox = {sess_dir / 'mailbox' / 'orchestrator' / 'inbox'}",
        file=sys.stderr,
    )
    return 0


# ------------------------------------------------------------------------ cleanup


def is_process_alive(pid: int) -> bool:
    """Return True iff the process exists and is not a zombie (defunct).

    On macOS (and other BSDs), kill(pid, 0) succeeds for zombie processes
    because they still hold a PID slot. We additionally check the process
    state via `ps` and treat state 'Z' (zombie/defunct) as dead so that
    dead-agent detection works for processes that have exited but whose
    parent hasn't reaped them yet.
    """
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    # pid exists — check whether it's a zombie (already exited, awaiting reap)
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "state="],
            capture_output=True, text=True, timeout=2,
        )
        state = result.stdout.strip()
        return bool(state) and state[0] != "Z"
    except Exception:
        # if ps fails for any reason, fall back to assuming alive
        return True


def cmd_cleanup(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    sess_dir = cwd / ".tmp" / "parallel-orchestrate" / args.session_tag
    manifest_path = sess_dir / "manifest.json"
    if not manifest_path.is_file():
        sys.exit(f"spawn-parallel: no manifest at {manifest_path}.")
    manifest = json.loads(manifest_path.read_text())

    repo_root = None
    if manifest["mode"] == "worktree":
        try:
            repo_root = Path(subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], cwd=cwd, text=True,
            ).strip())
        except subprocess.CalledProcessError:
            print("spawn-parallel: not in a git repo; skipping worktree removal.", file=sys.stderr)

    for s in manifest["spawns"]:
        # Kill the agent process if still alive — `--cleanup` is the user's
        # signal that the fanout is over, regardless of whether the agent
        # finished or hung.
        pid = s.get("pid")
        if pid and is_process_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"  signalled pid {pid} ({s['task_name']})", file=sys.stderr)
                time.sleep(0.5)
                if is_process_alive(pid):
                    os.kill(pid, signal.SIGKILL)
            except OSError as e:
                print(f"  warn: could not signal {pid}: {e}", file=sys.stderr)

        jp = Path(s["jsonl_path"])
        if jp.is_file():
            try:
                jp.unlink()
                print(f"  removed jsonl: {jp.name}", file=sys.stderr)
            except OSError as e:
                print(f"  warn: could not remove {jp}: {e}", file=sys.stderr)

        if args.remove_worktrees and repo_root and s.get("cwd"):
            wt = Path(s["cwd"])
            if wt.exists() and wt != repo_root:
                subprocess.run(
                    ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(wt)],
                    capture_output=True,
                )
                print(f"  removed worktree: {wt}", file=sys.stderr)

    if args.purge_session_dir:
        shutil.rmtree(sess_dir, ignore_errors=True)
        print(f"  purged session dir: {sess_dir}", file=sys.stderr)
    else:
        print(
            f"spawn-parallel: kept reports + manifest + mailbox at {sess_dir} "
            f"(use --purge-session-dir to delete).",
            file=sys.stderr,
        )
    return 0


# ------------------------------------------------------------------------ status


def cmd_status(args: argparse.Namespace) -> int:
    """Quick snapshot of a running fanout — alive procs, report counts, mailbox depth."""
    cwd = Path.cwd()
    sess_dir = cwd / ".tmp" / "parallel-orchestrate" / args.session_tag
    manifest_path = sess_dir / "manifest.json"
    if not manifest_path.is_file():
        sys.exit(f"spawn-parallel: no manifest at {manifest_path}.")
    manifest = json.loads(manifest_path.read_text())

    print(f"session: {args.session_tag}  mode={manifest['mode']}", file=sys.stderr)
    print(f"  orchestrator inbox: {len(list((sess_dir / 'mailbox' / 'orchestrator' / 'inbox').glob('*')))} unread",
          file=sys.stderr)
    print(f"  {'agent':<24} {'pid':>6}  {'alive':<5} {'report':<6} {'inbox':<5} {'branch'}", file=sys.stderr)
    for s in manifest["spawns"]:
        name = s["task_name"]
        pid = s.get("pid", 0)
        alive = "yes" if pid and is_process_alive(pid) else "no"
        report = (sess_dir / "reports" / f"{name}.md").is_file()
        inbox = sess_dir / "mailbox" / name / "inbox"
        inbox_count = len(list(inbox.glob("*"))) if inbox.is_dir() else 0
        print(
            f"  {name:<24} {pid:>6}  {alive:<5} {'yes' if report else 'no':<6} {inbox_count:<5} {s.get('branch', '')}",
            file=sys.stderr,
        )
    return 0


# ------------------------------------------------------------------------ watch


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
    seen_reports: set[str] = set()
    seen_msgs: set[str] = set()
    orch_inbox = sess_dir / "mailbox" / "orchestrator" / "inbox"

    dead_emitted: set[str] = set()
    alive_prev: dict[str, bool] = {
        a["name"]: is_process_alive(a.get("pid", 0)) for a in agents
    }

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

    # snapshot replay — emit for everything currently present, then begin loop
    reports_dir = sess_dir / "reports"
    if reports_dir.is_dir():
        for p in sorted(reports_dir.glob("*.md")):
            agent_name = p.stem
            emit("REPORT", agent_name, payload=str(p))
            seen_reports.add(agent_name)

    scan_msgs()

    while not _stop["flag"]:
        if reports_dir.is_dir():
            for p in sorted(reports_dir.glob("*.md")):
                if p.stem not in seen_reports:
                    emit("REPORT", p.stem, payload=str(p))
                    seen_reports.add(p.stem)

        scan_msgs()
        scan_dead()
        scan_silent()

        any_alive = any(is_process_alive(a.get("pid", 0)) for a in agents)
        if len(seen_reports) >= len(agents) and not any_alive:
            emit("ALL_DONE", payload=f"reports={len(seen_reports)}/{len(agents)} alive=0")
            return 0
        time.sleep(poll_sec)
    return 0


# ----------------------------------------------------------------------- argparse


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fork the current Claude session into N feature-branch agents (terminal-agnostic)."
    )
    ap.add_argument(
        "--session-tag", required=True,
        help="Short identifier for this fanout. Used for the .tmp/parallel-orchestrate/<tag>/ dir.",
    )
    ap.add_argument(
        "--task", action="append", default=[],
        help="One per fork. Format: 'name:prompt' or 'name:model:prompt'. Repeatable.",
    )
    ap.add_argument(
        "--mode", choices=["worktree", "shared"], default="worktree",
        help="worktree (default — each agent in its own git worktree + feature branch) | "
             "shared (all agents in orchestrator cwd; no branches).",
    )
    ap.add_argument(
        "--model", default="sonnet",
        help="Default model alias. Accepts opus, sonnet, haiku, opus-1m, sonnet-1m. "
             "Per-task override via 'name:model:prompt'. Default: sonnet.",
    )
    ap.add_argument(
        "--branch-prefix", default="feature",
        help="Branch name = <prefix>/<task-name>. Empty string = no prefix. Default: 'feature'.",
    )
    ap.add_argument(
        "--parent", default=None, metavar="UUID",
        help="REQUIRED. UUID of the orchestrator's session JSONL.",
    )
    ap.add_argument(
        "--stagger", type=float, default=2.0, metavar="SECS",
        help="Sleep between successive spawns to avoid hammering the Claude API "
             "during cold starts. Default: 2.0.",
    )

    ap.add_argument("--cleanup", action="store_true",
                    help="Tear down a fanout: kill procs, remove forked JSONLs.")
    ap.add_argument("--status", action="store_true",
                    help="Print current state of a fanout (alive procs, reports landed, inbox depth).")
    ap.add_argument("--remove-worktrees", action="store_true",
                    help="With --cleanup: also `git worktree remove` each fork's worktree.")
    ap.add_argument("--purge-session-dir", action="store_true",
                    help="With --cleanup: also delete .tmp/parallel-orchestrate/<tag>/ entirely.")

    ap.add_argument("--watch", action="store_true",
                    help="Stream structured event lines (REPORT/MSG/DEAD/SILENT/ALL_DONE) "
                         "to stdout until fanout completes. Designed for the Monitor tool.")
    ap.add_argument("--silent-min", type=float, default=5.0,
                    help="Minutes of no-log-growth before emitting SILENT (default 5.0).")
    ap.add_argument("--poll-sec", type=float, default=2.0,
                    help="Poll interval in seconds (default 2.0).")

    args = ap.parse_args()

    if args.cleanup:
        return cmd_cleanup(args)
    if args.status:
        return cmd_status(args)
    if args.watch:
        return cmd_watch(args)
    if not args.task:
        ap.error("one of --task (one or more), --status, --cleanup, or --watch is required")
    return cmd_spawn(args)


if __name__ == "__main__":
    sys.exit(main())
