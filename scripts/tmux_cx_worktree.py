#!/usr/bin/env python3
"""Open a tmux window with Codex on the right and its worktree on the left."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


DEFAULT_AGENT_COMMAND = (
    "zsh -lic 'cx --worktree; "
    "tmux set-option -p @cx_worktree_exited 1; exec zsh -l'"
)


def git_worktrees(repo: Path, managed_root: Path) -> set[Path]:
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    paths = {
        Path(line.removeprefix("worktree ")).resolve()
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    }
    return {
        path for path in paths
        if path.is_relative_to(managed_root) and path.name == repo.name
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.home() / "code/pintools")
    parser.add_argument("--managed-root", type=Path,
                        default=Path.home() / ".codex/worktrees")
    parser.add_argument("--name", default="pintools")
    parser.add_argument("--socket")
    parser.add_argument("--session")
    parser.add_argument("--pane")
    parser.add_argument("--agent-command", default=DEFAULT_AGENT_COMMAND)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    if not args.socket and not os.environ.get("TMUX"):
        parser.error("run from inside tmux or pass --socket and --session")
    repo = args.repo.expanduser().resolve()
    managed_root = args.managed_root.expanduser().resolve()
    if not repo.is_dir():
        parser.error(f"repository does not exist: {repo}")
    root = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if Path(root).resolve() != repo:
        parser.error(f"expected a repository root: {repo}")

    def tmux(*command: str) -> str:
        argv = ["tmux"]
        if args.socket:
            argv.extend(["-S", args.socket])
        result = subprocess.run(
            [*argv, *command], capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    session = args.session
    if not session:
        pane = args.pane or os.environ.get("TMUX_PANE")
        target = ["-t", pane] if pane else []
        session = tmux("display-message", "-p", *target, "#{session_id}")

    def report(message: str) -> None:
        print(message, file=sys.stderr)
        try:
            tmux("display-message", "-t", session, "-d", "10000", message)
        except subprocess.CalledProcessError:
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

        before = git_worktrees(repo, managed_root)
        right = None
        left = None
        try:
            window, right = tmux(
                "new-window", "-t", f"{session}:", "-c", str(repo),
                "-n", args.name, "-P", "-F", "#{window_id} #{pane_id}",
                args.agent_command,
            ).split()
            tmux("select-window", "-t", window)
            tmux("select-pane", "-t", right)

            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                added = git_worktrees(repo, managed_root) - before
                if len(added) > 1:
                    report("Multiple new Codex worktrees found; left pane will open in the base checkout")
                    return 1
                if added:
                    worktree = added.pop()
                    # Set the working directory before shell startup. Sending
                    # `cd` to a new shell races startup and directory hooks.
                    left = tmux(
                        "split-window", "-b", "-h", "-l", "33%", "-c", str(worktree),
                        "-t", right, "-P", "-F", "#{pane_id}",
                    )
                    tmux("select-pane", "-t", right)
                    return 0
                if tmux("display-message", "-p", "-t", right,
                        "#{@cx_worktree_exited}") == "1":
                    report("Codex exited before creating a worktree")
                    return 1
                time.sleep(0.5)
            report(
                f"No Codex worktree appeared after {args.timeout}s; "
                "left pane will open in the base checkout"
            )
            return 1
        except (OSError, subprocess.CalledProcessError, ValueError) as error:
            report(f"Could not set up the Codex worktree window: {error}")
            return 1
        finally:
            if right and left is None:
                try:
                    tmux(
                        "split-window", "-b", "-h", "-l", "33%", "-c", str(repo),
                        "-t", right,
                    )
                    tmux("select-pane", "-t", right)
                except (OSError, subprocess.CalledProcessError) as error:
                    report(f"Could not open the left pane in the base checkout: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
