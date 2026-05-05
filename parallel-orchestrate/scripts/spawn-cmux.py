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
import uuid
from pathlib import Path


# ---------------------------------------------------------------- shared helpers


def encode_project_path(p: Path) -> str:
    """Claude Code encodes the project path by replacing / and . with -."""
    return re.sub(r"[/.]", "-", str(p.resolve()))


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


def cmux_new_workspace(command: str, name: str) -> str:
    """Create a new cmux workspace running `command`. Returns the workspace ref.
    cmux prints the new ref to stdout; we capture it.
    """
    # `cmux new-workspace --command` runs the command in a shell inside the new workspace.
    # We then rename so the sidebar tab is human-readable.
    proc = subprocess.run(
        ["cmux", "new-workspace", "--command", command],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"spawn-cmux: cmux new-workspace failed:\n{proc.stderr.strip()}")
    # Best-effort parse — cmux output format may vary. Try JSON first, then look for workspace:N.
    ref = ""
    try:
        data = json.loads(proc.stdout)
        ref = data.get("workspace") or data.get("ref") or ""
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"workspace:\d+", proc.stdout)
        if m:
            ref = m.group(0)
    if not ref:
        # Workspace was created but we can't reference it programmatically.
        # The user can still see it; just warn.
        print(
            f"spawn-cmux: warn — could not parse workspace ref from cmux output for '{name}'. "
            f"You can still see the tab in the sidebar.",
            file=sys.stderr,
        )
    else:
        # Rename so the sidebar shows "<tag>:<name>" instead of the cwd.
        subprocess.run(
            ["cmux", "rename-workspace", "--workspace", ref, name],
            capture_output=True,
        )
    return ref


def cmux_close_workspace(ref: str) -> None:
    if not ref:
        return
    subprocess.run(
        ["cmux", "close-workspace", "--workspace", ref],
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
) -> dict:
    """Fork JSONL → place in target project dir → launch cmux workspace."""
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

    # Build the command cmux will run in the new workspace.
    # Note: `--resume <uuid>` resolves against the cwd's project dir, which we just populated.
    cd_part = f"cd {shell_quote(str(target_cwd))}"
    claude_part = (
        f"claude --resume {fork_uuid} --model {shell_quote(model)} "
        f"--permission-mode acceptEdits "  # forks need to actually edit; remove for stricter mode
        f"{shell_quote(prompt)}"
    )
    full = f"{cd_part} && {claude_part}"

    workspace_ref = cmux_new_workspace(full, name=f"{session_tag}:{task_name}")

    return {
        "task_name": task_name,
        "uuid": fork_uuid,
        "cwd": str(target_cwd),
        "branch": branch,
        "workspace_ref": workspace_ref,
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

    spawns: list[dict] = []
    for name, prompt in tasks:
        info = spawn_one(
            parent_jsonl=parent_jsonl,
            cwd=cwd,
            task_name=name,
            prompt=prompt,
            mode=args.mode,
            model=args.model,
            repo_root=repo_root,
            session_tag=args.session_tag,
        )
        spawns.append(info)
        print(
            f"  spawned {name:<24} uuid={info['uuid'][:8]} "
            f"workspace={info['workspace_ref'] or '?'} cwd={info['cwd']}",
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

        # Close the cmux workspace.
        if s.get("workspace_ref"):
            cmux_close_workspace(s["workspace_ref"])
            print(f"  closed cmux workspace: {s['workspace_ref']}", file=sys.stderr)

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
