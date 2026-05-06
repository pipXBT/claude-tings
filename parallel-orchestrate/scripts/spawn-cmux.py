#!/usr/bin/env python3
"""spawn-cmux — fork the current Claude session and launch one Opus agent per task
in its own cmux workspace tab, optionally inside its own git worktree.

Borrows the JSONL-snapshot trick from STRML/cc-skills/bin/cc-fork, but instead of
running `claude --resume <uuid> -p` and capturing stdout, each fork is launched as
`cmux new-workspace --command "cd <wt> && claude --resume <uuid> --model opus '<prompt>'"`
so it appears as a vertical sidebar tab the user can watch.

Usage:
    spawn-cmux.py --session-tag <tag> --task "name:prompt" --task "name:prompt" ...
    spawn-cmux.py --session-tag <tag> --mode {worktree,shared,dry-run} --model opus
    spawn-cmux.py --session-tag <tag> --cleanup [--remove-worktrees]

Modes:
    worktree   each agent in its own `git worktree add`. Default. Safest.
    shared     all agents share the orchestrator's working tree. File-ownership boundaries.
    dry-run    no worktree, no edits expected; agents propose patches in their reports.

Requires:
    - cmux running (CMUX_WORKSPACE_ID env var set)
    - claude CLI on PATH
    - git repo cwd (for worktree mode)
    - Python 3.8+
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


# ---------------------------------------------------------------- shared helpers


def encode_project_path(p: Path) -> str:
    """Claude Code encodes the project path by replacing /, ., and space with -."""
    return re.sub(r"[/. ]", "-", str(p.resolve()))


def claude_project_dir(cwd: Path) -> Path:
    return Path.home() / ".claude" / "projects" / encode_project_path(cwd)


def find_parent_jsonl(project_dir: Path) -> Path:
    """Largest .jsonl in the project dir is almost always the live conversation.
    Sidecar files are tiny; the live JSONL grows with every turn."""
    if not project_dir.is_dir():
        sys.exit(
            f"spawn-cmux: no Claude session dir at {project_dir}. "
            f"Start a session in this cwd first."
        )
    candidates = [
        f for f in project_dir.glob("*.jsonl")
        if f.stat().st_size > 500  # skip empty/sidecar files
    ]
    if not candidates:
        sys.exit(
            f"spawn-cmux: no substantive JSONL in {project_dir}. "
            f"Start a Claude session in this cwd first."
        )
    return max(candidates, key=lambda f: f.stat().st_size)


def require(cmd: str) -> None:
    if shutil.which(cmd) is None:
        sys.exit(f"spawn-cmux: required binary `{cmd}` not on PATH.")


def require_cmux() -> None:
    if not os.environ.get("CMUX_WORKSPACE_ID"):
        sys.exit(
            "spawn-cmux: CMUX_WORKSPACE_ID is not set — you are not running inside cmux. "
            "Launch a cmux terminal and re-run."
        )
    require("cmux")


def session_dir(cwd: Path, tag: str) -> Path:
    """Where the manifest and reports live, relative to the orchestrator cwd."""
    d = cwd / ".tmp" / "parallel-orchestrate" / tag
    d.mkdir(parents=True, exist_ok=True)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    return d


def parse_task(raw: str) -> tuple[str, str]:
    """Split 'name:prompt' on the first colon. Validate name shape."""
    if ":" not in raw:
        sys.exit(f"spawn-cmux: --task must be 'name:prompt', got: {raw[:40]}…")
    name, prompt = raw.split(":", 1)
    name = name.strip()
    prompt = prompt.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", name):
        sys.exit(
            f"spawn-cmux: task name '{name}' must be lowercase alnum + - / _, ≤41 chars. "
            f"It becomes a git branch and a worktree dir."
        )
    if not prompt:
        sys.exit(f"spawn-cmux: task '{name}' has empty prompt.")
    return name, prompt


# --------------------------------------------------------------------- worktree


def make_worktree(repo_root: Path, session_tag: str, task_name: str) -> tuple[Path, str]:
    """Create a worktree at <repo>/../<repo>-worktrees/<tag>/<task_name>
    on a fresh branch parallel/<tag>/<task_name>.
    Returns (worktree_path, branch_name).
    """
    wt_root = repo_root.parent / f"{repo_root.name}-worktrees" / session_tag
    wt_root.mkdir(parents=True, exist_ok=True)
    wt_path = wt_root / task_name
    branch = f"parallel/{session_tag}/{task_name}"

    if wt_path.exists():
        sys.exit(
            f"spawn-cmux: worktree already exists at {wt_path}. "
            f"Run --cleanup first or pick a different --session-tag."
        )

    # Create the branch from current HEAD and add the worktree in one shot.
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b", branch, str(wt_path)],
        check=True,
    )
    return wt_path, branch


def list_worktrees(repo_root: Path) -> list[dict]:
    """Parse `git worktree list --porcelain` into dicts."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        check=True, capture_output=True, text=True,
    ).stdout
    blocks = [b for b in out.split("\n\n") if b.strip()]
    result = []
    for b in blocks:
        d = {}
        for line in b.splitlines():
            if " " in line:
                k, v = line.split(" ", 1)
            else:
                k, v = line, ""
            d[k] = v
        result.append(d)
    return result


# ------------------------------------------------------------------------ cmux


def cmux_current_pane() -> str:
    """Return the orchestrator's current pane ref via `cmux identify`.
    Each spawned terminal tab is added to this pane so the user sees them
    as new tabs alongside the orchestrator, not in a separate workspace.
    """
    proc = subprocess.run(
        ["cmux", "identify", "--no-caller"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"spawn-cmux: cmux identify failed:\n{proc.stderr.strip()}")
    try:
        data = json.loads(proc.stdout)
        pane = data.get("focused", {}).get("pane_ref", "")
    except (json.JSONDecodeError, ValueError):
        pane = ""
    if not pane:
        sys.exit("spawn-cmux: cmux identify did not return a focused pane_ref.")
    return pane


def cmux_new_terminal_tab(command: str, name: str, pane: str) -> str:
    """Create a new terminal tab (surface) in the given pane, send `command`
    + Enter to execute it, and rename the tab so the sidebar shows `name`.
    Returns the new surface ref.

    Pattern: `cmux new-surface --type terminal --pane <pane>` returns
    "OK surface:N pane:M workspace:K"; we parse out surface:N. Then
    `cmux send <text>` types the command, `cmux send-key Enter` executes
    it, and `cmux rename-tab` updates the tab title.
    """
    proc = subprocess.run(
        ["cmux", "new-surface", "--type", "terminal", "--pane", pane],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"spawn-cmux: cmux new-surface failed:\n{proc.stderr.strip()}")
    m = re.search(r"surface:\d+", proc.stdout)
    if not m:
        sys.exit(
            f"spawn-cmux: could not parse surface ref from cmux output: {proc.stdout!r}"
        )
    ref = m.group(0)

    # The new terminal needs a moment to spin up its shell before it can
    # accept keystrokes. 0.5s empirically reliable on M-series Macs;
    # longer is safe but slows fanout.
    time.sleep(0.5)

    subprocess.run(
        ["cmux", "send", "--surface", ref, command],
        capture_output=True,
    )
    subprocess.run(
        ["cmux", "send-key", "--surface", ref, "Enter"],
        capture_output=True,
    )
    subprocess.run(
        ["cmux", "rename-tab", "--surface", ref, name],
        capture_output=True,
    )
    return ref


def cmux_close_surface(ref: str) -> None:
    if not ref:
        return
    subprocess.run(
        ["cmux", "close-surface", "--surface", ref],
        capture_output=True,
    )


# ------------------------------------------------------------------------ spawn


def shell_quote(s: str) -> str:
    """Single-quote-safe shell quoting. Replaces ' with '\\''."""
    return "'" + s.replace("'", "'\\''") + "'"


def spawn_one(
    parent_jsonl: Path,
    cwd: Path,
    task_name: str,
    prompt: str,
    mode: str,
    model: str,
    repo_root: Path,
    session_tag: str,
    pane_ref: str,
) -> dict:
    """Fork JSONL → place in target project dir → launch terminal tab in
    the orchestrator's pane and start `claude --resume <uuid>` inside it.
    """
    fork_uuid = str(uuid.uuid4())
    branch = ""
    if mode == "worktree":
        wt_path, branch = make_worktree(repo_root, session_tag, task_name)
        target_cwd = wt_path
    else:
        target_cwd = cwd

    # Parent JSONL must land in the target cwd's encoded project dir,
    # so `claude --resume <uuid>` finds it when launched from there.
    target_proj_dir = claude_project_dir(target_cwd)
    target_proj_dir.mkdir(parents=True, exist_ok=True)
    target_jsonl = target_proj_dir / f"{fork_uuid}.jsonl"
    shutil.copy2(parent_jsonl, target_jsonl)

    # Build the shell command we'll send to the new terminal tab.
    # `--resume <uuid>` resolves against the cwd's project dir we just populated.
    cd_part = f"cd {shell_quote(str(target_cwd))}"
    claude_part = (
        f"claude --resume {fork_uuid} --model {shell_quote(model)} "
        f"--dangerously-skip-permissions "
        f"{shell_quote(prompt)}"
    )
    full = f"{cd_part} && {claude_part}"

    surface_ref = cmux_new_terminal_tab(
        full, name=f"{session_tag}:{task_name}", pane=pane_ref
    )

    return {
        "task_name": task_name,
        "uuid": fork_uuid,
        "cwd": str(target_cwd),
        "branch": branch,
        "surface_ref": surface_ref,
        "jsonl_path": str(target_jsonl),
    }


def cmd_spawn(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    require_cmux()
    require("claude")

    if args.mode == "worktree":
        require("git")
        # repo_root = git toplevel
        try:
            repo_root = Path(subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], cwd=cwd, text=True,
            ).strip())
        except subprocess.CalledProcessError:
            sys.exit("spawn-cmux: --mode worktree requires a git repo (not in one).")
    else:
        repo_root = cwd

    parent_jsonl = find_parent_jsonl(claude_project_dir(cwd))
    print(
        f"spawn-cmux: parent session = {parent_jsonl.name} "
        f"({parent_jsonl.stat().st_size // 1024}K)",
        file=sys.stderr,
    )

    sess_dir = session_dir(cwd, args.session_tag)
    manifest_path = sess_dir / "manifest.json"
    if manifest_path.exists():
        sys.exit(
            f"spawn-cmux: manifest already exists at {manifest_path}. "
            f"Run --cleanup or pick a different --session-tag."
        )

    tasks = [parse_task(t) for t in args.task]
    print(f"spawn-cmux: {len(tasks)} task(s), mode={args.mode}, model={args.model}", file=sys.stderr)

    pane_ref = cmux_current_pane()
    print(f"spawn-cmux: tabs will land in pane {pane_ref}", file=sys.stderr)

    spawns: list[dict] = []
    for i, (name, prompt) in enumerate(tasks):
        if i > 0 and args.stagger > 0:
            print(f"spawn-cmux: sleeping {args.stagger}s before next spawn", file=sys.stderr)
            time.sleep(args.stagger)
        info = spawn_one(
            parent_jsonl=parent_jsonl,
            cwd=cwd,
            task_name=name,
            prompt=prompt,
            mode=args.mode,
            model=args.model,
            repo_root=repo_root,
            session_tag=args.session_tag,
            pane_ref=pane_ref,
        )
        spawns.append(info)
        print(
            f"  spawned {name:<24} uuid={info['uuid'][:8]} "
            f"surface={info['surface_ref'] or '?'} cwd={info['cwd']}",
            file=sys.stderr,
        )

    manifest = {
        "session_tag": args.session_tag,
        "mode": args.mode,
        "model": args.model,
        "orchestrator_cwd": str(cwd),
        "parent_jsonl": str(parent_jsonl),
        "spawns": spawns,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"spawn-cmux: manifest written to {manifest_path}", file=sys.stderr)

    # Sidebar status update so the orchestrator tab reflects state.
    subprocess.run(
        ["cmux", "set-status", "orchestrate",
         f"{args.session_tag}: {len(spawns)} agent(s) in flight",
         "--icon", "hammer", "--color", "#1565C0"],
        capture_output=True,
    )
    return 0


# ------------------------------------------------------------------------ cleanup


def cmd_cleanup(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    sess_dir = cwd / ".tmp" / "parallel-orchestrate" / args.session_tag
    manifest_path = sess_dir / "manifest.json"
    if not manifest_path.is_file():
        sys.exit(f"spawn-cmux: no manifest at {manifest_path}.")
    manifest = json.loads(manifest_path.read_text())

    repo_root = None
    if manifest["mode"] == "worktree":
        try:
            repo_root = Path(subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], cwd=cwd, text=True,
            ).strip())
        except subprocess.CalledProcessError:
            print("spawn-cmux: not in a git repo; skipping worktree removal.", file=sys.stderr)

    for s in manifest["spawns"]:
        # Remove the forked JSONL.
        jp = Path(s["jsonl_path"])
        if jp.is_file():
            try:
                jp.unlink()
                print(f"  removed jsonl: {jp.name}", file=sys.stderr)
            except OSError as e:
                print(f"  warn: could not remove {jp}: {e}", file=sys.stderr)

        # Close the cmux terminal tab. Tolerate the legacy workspace_ref
        # field too in case a manifest from an older script run is being
        # cleaned up.
        ref = s.get("surface_ref") or s.get("workspace_ref")
        if ref:
            if ref.startswith("surface:"):
                cmux_close_surface(ref)
                print(f"  closed cmux tab: {ref}", file=sys.stderr)
            else:
                # Legacy: this manifest was written by an older script
                # version that created workspaces. Close as workspace.
                subprocess.run(
                    ["cmux", "close-workspace", "--workspace", ref],
                    capture_output=True,
                )
                print(f"  closed cmux workspace: {ref}", file=sys.stderr)

        # Optionally remove the worktree.
        if args.remove_worktrees and repo_root and s.get("cwd"):
            wt = Path(s["cwd"])
            if wt.exists() and wt != repo_root:
                subprocess.run(
                    ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(wt)],
                    capture_output=True,
                )
                print(f"  removed worktree: {wt}", file=sys.stderr)

    # Clear orchestrator status.
    subprocess.run(["cmux", "clear-status", "orchestrate"], capture_output=True)

    if args.purge_session_dir:
        shutil.rmtree(sess_dir, ignore_errors=True)
        print(f"  purged session dir: {sess_dir}", file=sys.stderr)
    else:
        print(
            f"spawn-cmux: kept reports + manifest at {sess_dir} "
            f"(use --purge-session-dir to delete).",
            file=sys.stderr,
        )
    return 0


# ----------------------------------------------------------------------- argparse


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fork the current Claude session and launch one Opus agent per task in cmux."
    )
    ap.add_argument(
        "--session-tag", required=True,
        help="Short identifier for this fanout (e.g. 'feat-auth'). Used for branch names, "
             "worktree paths, cmux workspace names, and the report dir.",
    )

    # Flat flags — no subcommand. Default action is spawn; --cleanup switches to teardown.
    ap.add_argument(
        "--task", action="append", default=[],
        help="One per fork. Format: 'name:prompt'. Repeatable.",
    )
    ap.add_argument(
        "--mode", choices=["worktree", "shared", "dry-run"], default="worktree",
        help="worktree (default) | shared | dry-run.",
    )
    ap.add_argument(
        "--model", default="opus",
        help="Model alias passed to claude --model. Default: opus.",
    )
    ap.add_argument(
        "--stagger", type=float, default=0.0, metavar="SECS",
        help="Sleep this many seconds between successive spawns. Useful when the "
             "Anthropic API rate-limits bursts of fork start-ups, or when the user "
             "wants visual cadence in the cmux sidebar.",
    )

    # Cleanup flags.
    ap.add_argument(
        "--cleanup", action="store_true",
        help="Tear down a previous fanout: remove forked JSONLs and close cmux workspaces.",
    )
    ap.add_argument(
        "--remove-worktrees", action="store_true",
        help="With --cleanup: also `git worktree remove` each fork's worktree.",
    )
    ap.add_argument(
        "--purge-session-dir", action="store_true",
        help="With --cleanup: also delete .tmp/parallel-orchestrate/<tag>/ entirely.",
    )

    args = ap.parse_args()

    if args.cleanup:
        return cmd_cleanup(args)
    if not args.task:
        ap.error("either --cleanup or one or more --task is required")
    return cmd_spawn(args)


if __name__ == "__main__":
    sys.exit(main())
