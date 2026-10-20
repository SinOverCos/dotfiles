#!/usr/bin/env python3
"""Open a tmux window with Codex on the right and its worktree on the left."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from tmux_cx_cleanup import git, start_watcher


def refresh_base(repo: Path) -> str:
    branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if git(repo, "remote").splitlines().count("origin"):
        remote_head = subprocess.run(
            ["git", "-C", str(repo), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        base = remote_head.removeprefix("origin/")
        if not base:
            base = next((name for name in ("main", "master") if subprocess.run(
                ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{name}"],
                capture_output=True, check=False,
            ).returncode == 0), branch)
        if branch == base:
            git(repo, "pull", "--ff-only", "origin", base)
        else:
            git(repo, "fetch", "origin", f"{base}:{base}")
        return git(repo, "rev-parse", base)
    return git(repo, "rev-parse", "HEAD")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.home() / "code/pintools")
    parser.add_argument("--managed-root", type=Path,
                        default=Path.home() / ".codex/worktrees")
    parser.add_argument("--name", default="pintools")
    parser.add_argument("--socket")
    parser.add_argument("--session")
    parser.add_argument("--pane")
    parser.add_argument("--agent-command", help="override the command run in the new worktree")
    args = parser.parse_args()

    if not args.socket and not os.environ.get("TMUX"):
        parser.error("run from inside tmux or pass --socket and --session")
    repo = args.repo.expanduser().resolve()
    managed_root = args.managed_root.expanduser().resolve()
    if not repo.is_dir() or Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        parser.error(f"expected a repository root: {repo}")

    def tmux(*command: str) -> str:
        argv = ["tmux"]
        if args.socket:
            argv.extend(["-S", args.socket])
        return subprocess.run(
            [*argv, *command], capture_output=True, text=True, check=True, timeout=15,
        ).stdout.strip()

    session = args.session
    if not session:
        pane = args.pane or os.environ.get("TMUX_PANE")
        target = ["-t", pane] if pane else []
        session = tmux("display-message", "-p", *target, "#{session_id}")
    socket = tmux("display-message", "-p", "-t", session, "#{socket_path}")

    def report(message: str) -> None:
        print(message, file=sys.stderr)
        try:
            tmux("display-message", "-t", session, "-d", "10000", message)
        except subprocess.SubprocessError:
            pass

    lock_name = hashlib.sha256(str(repo).encode()).hexdigest()[:12]
    lock_path = Path(tempfile.gettempdir()) / (
        f"tmux-cx-worktree-{os.getuid()}-{lock_name}.lock"
    )
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            report("A Codex worktree window is already being set up")
            return 1

        worktree = None
        window = None
        try:
            base_head = refresh_base(repo)
            managed_root.mkdir(parents=True, exist_ok=True)
            container = Path(tempfile.mkdtemp(prefix="tmux-", dir=managed_root))
            worktree = container / repo.name
            # Allocate this exact worktree ourselves. Watching additions to the
            # repository could adopt a concurrently created session's worktree.
            git(repo, "worktree", "add", "--detach", str(worktree), base_head)
            command = args.agent_command
            if command is None:
                shell = (
                    f"cx; cd -- {shlex.quote(str(repo))}; "
                    "tmux set-option -p @cx_worktree_exited 1; exec zsh -l"
                )
                command = "zsh -lic " + shlex.quote(shell)
            window, right = tmux(
                "new-window", "-t", f"{session}:", "-c", str(worktree),
                "-n", args.name, "-P", "-F", "#{window_id} #{pane_id}", command,
            ).split()
            tmux("set-option", "-w", "-t", window, "@cx_worktree", str(worktree))
            state = start_watcher(
                repo, worktree, managed_root, base_head, socket, window, right,
            )
            tmux("set-option", "-w", "-t", window, "@cx_cleanup_state", str(state))
            tmux("split-window", "-b", "-h", "-l", "33%", "-c", str(worktree), "-t", right)
            tmux("select-window", "-t", window)
            tmux("select-pane", "-t", right)
            return 0
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
            detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
            report(f"Could not open the Codex worktree window: {detail}")
            if worktree is not None and window is None:
                # No agent was started, so only our unused checkout can be removed.
                try:
                    git(repo, "worktree", "remove", str(worktree))
                    worktree.parent.rmdir()
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    report(f"Retained unused worktree for inspection: {worktree}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
