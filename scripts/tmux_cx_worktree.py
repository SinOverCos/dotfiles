#!/usr/bin/env python3
"""Open a tmux window with Codex on the right and its worktree on the left."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import termios
import threading
import time
from typing import Iterator, TextIO

from tmux_cx_cleanup import git, start_watcher


def write_setup_state(path: Path, status: str, detail: str) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"status": status, "detail": detail, "pid": os.getpid()}) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def wait_for_setup(path: Path) -> int:
    while True:
        setup = json.loads(path.read_text())
        if setup["status"] == "ready":
            print("Repository ready.")
            return 0
        if setup["status"] == "failed":
            print(f"Repository loading failed: {setup['detail']}", file=sys.stderr)
            return 1
        try:
            os.kill(setup["pid"], 0)
        except ProcessLookupError:
            print("Repository loader stopped before finishing.", file=sys.stderr)
            return 1
        time.sleep(0.1)


def startup_instructions(state: Path) -> str:
    # Inline the tiny readiness check so agents inside ai-sandbox do not need
    # access to the host's dotfiles checkout.
    wait = (
        "import json,sys,time\n"
        "deadline=time.monotonic()+180\n"
        "while True:\n"
        " s=json.load(open(sys.argv[1]))\n"
        " if s['status']=='ready': break\n"
        " if s['status']=='failed': raise SystemExit('Repository loading failed: '+s['detail'])\n"
        " if time.monotonic()>deadline: raise SystemExit('Repository loading did not finish; inspect the loading pane.')\n"
        " time.sleep(0.1)\n"
    )
    command = shlex.join(["python3", "-c", wait, str(state)])
    return (
        "The repository is loading in the background in your current working directory. "
        "The user can type and discuss the task immediately. Before your first repository "
        "read, search, edit, test, build, or Git operation, run this readiness check and "
        "require success:\n\n```sh\n" + command + "\n```\n\nDo not interpret paths absent during loading "
        "as missing project files. If loading fails, report the failure and preserve "
        "the working tree. Once ready, read applicable nested agent instructions normally."
    )


def prepare_initial_files(repo: Path, worktree: Path, base_head: str) -> None:
    git(repo, "worktree", "add", "--detach", "--no-checkout", str(worktree), base_head, timeout=120)
    # Cone mode also includes root files, so both agents can discover the actual
    # repo instructions and tool configuration without checking out app assets.
    git(worktree, "sparse-checkout", "set", "--cone", ".agents", ".claude", ".codex")
    git(worktree, "read-tree", "-mu", "HEAD")


def follow_setup_log(path: Path, owner_pid: int | None = None) -> int:
    def stop(_number: int, _frame: object) -> None:
        raise SystemExit(0)

    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, stop)
    original_terminal = None
    if sys.stdin.isatty():
        original_terminal = termios.tcgetattr(sys.stdin.fileno())
        terminal = original_terminal.copy()
        terminal[3] &= ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, terminal)
    try:
        with path.open() as log:
            while True:
                content = log.read()
                if content:
                    print(content, end="", flush=True)
                time.sleep(0.1)
    except FileNotFoundError:
        return 0
    finally:
        if original_terminal is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, original_terminal)
            except termios.error:
                pass
        try:
            if owner_pid is not None:
                os.kill(owner_pid, 0)
            else:
                path.unlink(missing_ok=True)
        except ProcessLookupError:
            path.unlink(missing_ok=True)


@contextmanager
def progress(log: TextIO, label: str) -> Iterator[None]:
    started = time.monotonic()
    finished = threading.Event()
    log.write(f"{label}...\n")

    def heartbeat() -> None:
        while not finished.wait(3):
            log.write(f"{label} ({time.monotonic() - started:.0f}s elapsed)...\n")

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        yield
    finally:
        finished.set()
        worker.join()
    log.write(f"{label} completed in {time.monotonic() - started:.1f}s.\n")


def refresh_base(repo: Path) -> str:
    branch = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True, text=True, check=False, timeout=30,
    ).stdout.strip()
    if not branch:
        raise RuntimeError(
            f"The base checkout is detached: {repo}\n"
            "Switch it back to its base branch, then retry."
        )
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
            git(repo, "pull", "--ff-only", "origin", base, timeout=120)
        else:
            git(repo, "fetch", "origin", f"{base}:{base}", timeout=120)
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
    parser.add_argument("--agent", choices=("codex", "claude"), default="codex")
    parser.add_argument("--follow-setup-log", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--log-owner-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--wait-setup", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.follow_setup_log:
        return follow_setup_log(args.follow_setup_log, args.log_owner_pid)
    if args.wait_setup:
        return wait_for_setup(args.wait_setup)

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
        container = None
        window = None
        watching = False
        agent_started = False
        setup_state = None
        complete = False
        started = time.monotonic()
        log_fd, log_name = tempfile.mkstemp(prefix="tmux-cx-setup-", suffix=".log")
        setup_log = Path(log_name)
        with os.fdopen(log_fd, "w", buffering=1) as log:
            try:
                log.write(
                    "Starting agent. Wait for its input prompt before typing.\n"
                    "Keys typed before the prompt are discarded.\n"
                    "Repository files will continue loading in the background.\n"
                )
                # Each follower holds an open descriptor, so closing either pane
                # can unlink the temporary log without interrupting the other.
                waiting = "exec " + shlex.join([
                    sys.executable, str(Path(__file__).resolve()),
                    "--follow-setup-log", str(setup_log),
                    "--log-owner-pid", str(os.getpid()),
                ])
                # Show both panes before network access or the large checkout.
                # These noninteractive placeholders do not run shell startup hooks.
                window, right = tmux(
                    "new-window", "-t", f"{session}:", "-c", str(repo),
                    "-n", args.name, "-P", "-F", "#{window_id} #{pane_id}", waiting,
                ).split()
                left = tmux(
                    "split-window", "-b", "-h", "-l", "33%", "-c", str(repo), "-t", right,
                    "-P", "-F", "#{pane_id}", waiting,
                )
                tmux("set-option", "-w", "-t", window, "@cx_setup_log", str(setup_log))
                tmux("select-pane", "-t", right)

                def require_setup_panes() -> None:
                    for pane, side in ((left, "left"), (right, "right")):
                        if tmux("display-message", "-p", "-t", pane, "#{pane_id}") != pane:
                            raise RuntimeError(f"The {side} setup pane was closed.")

                with progress(log, "Updating base branch"):
                    base_head = refresh_base(repo)
                # A user may close the loading window while Git is running.
                require_setup_panes()
                managed_root.mkdir(parents=True, exist_ok=True)
                container = Path(tempfile.mkdtemp(prefix="tmux-", dir=managed_root))
                worktree = container / repo.name
                # Allocate this exact worktree ourselves, never adopt another session's.
                with progress(log, "Preparing agent instructions"):
                    prepare_initial_files(repo, worktree, base_head)
                require_setup_panes()
                tmux("set-option", "-w", "-t", window, "@cx_worktree", str(worktree))
                setup_state = Path(git(worktree, "rev-parse", "--absolute-git-dir")) / "tmux-setup.json"
                write_setup_state(setup_state, "loading", "Loading repository files")
                state = start_watcher(
                    repo, worktree, managed_root, base_head, socket, window, right, setup_state,
                    cleanup_pintools=True,
                )
                watching = True
                tmux("set-option", "-w", "-t", window, "@cx_cleanup_state", str(state))
                require_setup_panes()
                command = args.agent_command
                if command is None:
                    instructions = startup_instructions(setup_state)
                    if args.agent == "claude":
                        agent = "cc --append-system-prompt " + shlex.quote(instructions)
                    else:
                        agent = "cx -c " + shlex.quote("developer_instructions=" + json.dumps(instructions))
                    shell = (
                        f"{agent}; unset PINTOOLS_READ_ONLY; cd -- {shlex.quote(str(repo))}; "
                        "tmux set-option -p @cx_worktree_exited 1; exec zsh -l"
                    )
                    command = "zsh -lic " + shlex.quote(shell)
                # PinTools already supports this guard for dependency-free shells.
                # Explicit pnpm installs still work; each worktree keeps its own deps.
                tmux(
                    "respawn-pane", "-k", "-t", right, "-c", str(worktree),
                    "-e", "PINTOOLS_READ_ONLY=1", command,
                )
                agent_started = True
                tmux("set-option", "-w", "-t", window, "@cx_agent_seconds", f"{time.monotonic() - started:.3f}")
                # Source expansion uses this worktree's own index. Let the next
                # window refresh/allocate its checkout while this one loads.
                fcntl.flock(lock, fcntl.LOCK_UN)
                log.write("Agent open. You can type now while repository files load.\n")
                # This runs while the live agent accepts input. Never respawn
                # its pane when expansion finishes: that would erase drafts.
                with progress(log, "Loading repository files"):
                    git(worktree, "sparse-checkout", "disable", timeout=120)
                elapsed = time.monotonic() - started
                banner = f"Repository ready ({elapsed:.1f}s).\nInstall dependencies when needed."
                if tmux("display-message", "-p", "-t", left, "#{pane_id}") == left:
                    tmux(
                        "respawn-pane", "-k", "-t", left, "-c", str(worktree),
                        "-e", "PINTOOLS_READ_ONLY=1",
                        "printf '%s\\n' " + shlex.quote(banner) + "; exec zsh -l",
                    )
                tmux("set-option", "-w", "-t", window, "@cx_setup_seconds", f"{elapsed:.3f}")
                tmux("set-option", "-w", "-t", window, "-u", "@cx_setup_log")
                write_setup_state(setup_state, "ready", "Repository ready")
                complete = True
                return 0
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
                detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
                message = (
                    f"Repository loading failed: {detail}" if agent_started
                    else f"Could not open the {args.agent} worktree window: {detail}"
                )
                heading = "Repository loading failed. Your agent is still open." if agent_started else "Setup failed."
                log.write(
                    f"\n{heading}\nPress Ctrl-q to close this window.\n"
                    f"Then Ctrl-a Ctrl-w to retry.\n\n{detail}\n"
                )
                report(message)
                if setup_state is not None:
                    write_setup_state(setup_state, "failed", detail)
                if agent_started:
                    # The agent may already have written files. Let the existing
                    # watcher inspect it after all panes leave, never remove here.
                    return 1
                if worktree is not None and not watching:
                    # Only placeholders have run; Git still performs its dirty check.
                    try:
                        git(repo, "worktree", "remove", str(worktree))
                    except (OSError, RuntimeError, subprocess.SubprocessError):
                        if worktree.exists():
                            notice = f"Retained unused worktree for inspection: {worktree}"
                            log.write(notice + "\n")
                            report(notice)
                    if container is not None:
                        try:
                            container.rmdir()
                        except OSError:
                            pass
                return 1
            finally:
                if not complete and window is not None:
                    try:
                        visible = window in tmux("list-windows", "-a", "-F", "#{window_id}").splitlines()
                    except subprocess.SubprocessError:
                        visible = False
                    if not visible:
                        setup_log.unlink(missing_ok=True)
                if complete or window is None:
                    setup_log.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
