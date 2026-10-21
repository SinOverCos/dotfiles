#!/usr/bin/env python3
"""Watch one Codex tmux window from outside its panes and clean its worktree."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid


DISPOSABLE_DIRECTORIES = (
    "node_modules", "dist", ".turbo", ".vite", "coverage", "__pycache__", ".pytest_cache",
)


@dataclass
class Watch:
    repo: str
    worktree: str
    managed_root: str
    base_head: str
    git_dir: str
    worktree_identity: list[int]
    socket: str
    socket_identity: list[int]
    server_pid: int
    window: str
    agent_pane: str
    setup_state: str = ""
    cleanup_pintools: bool = False


def identity(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_dev, stat.st_ino]


def git(path: Path, *args: str, timeout: float = 30) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True,
        check=False, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Git command failed with status {result.returncode}")
    return result.stdout.rstrip("\n")


def record(path: Path, watch: Watch, status: str, detail: str) -> None:
    data = asdict(watch) | {
        "pid": os.getpid(), "status": status, "detail": detail,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
    print(f"{status}: {watch.worktree}: {detail}", flush=True)


def start_watcher(
    repo: Path, worktree: Path, managed_root: Path, base_head: str,
    socket: str, window: str, agent_pane: str,
    setup_state: Path | None = None,
    cleanup_pintools: bool = False,
) -> Path:
    watch = Watch(
        str(repo), str(worktree), str(managed_root), base_head,
        git(worktree, "rev-parse", "--absolute-git-dir"), identity(worktree),
        socket, identity(Path(socket)), int(subprocess.run(
            ["tmux", "-S", socket, "display-message", "-p", "#{pid}"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()), window, agent_pane, str(setup_state) if setup_state else "",
        cleanup_pintools,
    )
    directory = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    directory = directory / "tmux-cx-worktree"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = directory / f"{uuid.uuid4().hex}.json"
    state.write_text(json.dumps(asdict(watch)) + "\n")
    state.chmod(0o600)
    with state.with_suffix(".log").open("w") as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--watch", str(state)],
            cwd=repo, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    return state


def server_stopped(watch: Watch) -> bool:
    if watch.server_pid <= 0:
        raise RuntimeError("invalid tmux server identity")
    for _ in range(20):
        try:
            os.kill(watch.server_pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def panes(watch: Watch) -> list[list[str]]:
    socket_path = Path(watch.socket)
    if not socket_path.exists():
        if server_stopped(watch):
            return []
        raise RuntimeError("tmux socket is missing but its server is still running")
    if identity(socket_path) != watch.socket_identity:
        raise RuntimeError("tmux server was replaced; retained the worktree")
    result = subprocess.run(
        ["tmux", "-S", watch.socket, "list-panes", "-a", "-F",
         "#{window_id}\t#{pane_id}\t#{pane_current_path}\t#{@cx_worktree_exited}"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode:
        # Closing the final window can leave a socket file. Check the original
        # server process, rather than treating every connection failure as exit.
        if server_stopped(watch):
            return []
        raise RuntimeError("could not inspect tmux panes; retained the worktree")
    rows = [line.split("\t") for line in result.stdout.splitlines()]
    if any(len(row) != 4 for row in rows):
        raise RuntimeError("could not identify tmux pane directories")
    return rows


def ready(watch: Watch, rows: list[list[str]]) -> bool:
    if watch.setup_state:
        setup = json.loads(Path(watch.setup_state).read_text())
        if setup["status"] == "loading":
            try:
                os.kill(setup["pid"], 0)
            except ProcessLookupError:
                raise RuntimeError("repository loader stopped before finishing; retained the worktree")
            return False
        if setup["status"] not in {"ready", "failed"}:
            raise RuntimeError("repository loading state is unknown")
    agent = next((row for row in rows if row[1] == watch.agent_pane), None)
    if agent is not None and agent[3] != "1":
        return False
    if any(not row[2] or not Path(row[2]).is_absolute() for row in rows):
        return False
    worktree = Path(watch.worktree)
    return not any(Path(row[2]).resolve().is_relative_to(worktree) for row in rows)


def pintools_resources(worktree: Path, directory: Path | None = None) -> tuple[list[dict], list[dict]]:
    directory = directory or Path.home() / ".pintools/dev-instances"
    owned = []
    for name in ("registry.json", "databases.json"):
        path = directory / name
        if not path.exists():
            owned.append([])
            continue
        try:
            data = json.loads(path.read_text())
            rows = data["instances"] if name == "registry.json" else data
            if not isinstance(rows, list):
                raise ValueError("invalid resource list")
            matching = []
            for row in rows:
                if (
                    not isinstance(row, dict) or not isinstance(row.get("checkout"), str)
                    or not Path(row["checkout"]).is_absolute()
                ):
                    raise ValueError("invalid resource ownership")
                if Path(row["checkout"]).resolve() != worktree:
                    continue
                matching.append(row)
            owned.append(matching)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeError("could not verify PinTools resource ownership; retained the worktree") from error
    return owned[0], owned[1]


def check_pintools_resources(worktree: Path, directory: Path | None = None) -> None:
    instances, databases = pintools_resources(worktree, directory)
    if (
        any(row.get("status") not in {"stopped", "failed"} for row in instances)
        or any(row.get("state") != "released" for row in databases)
    ):
        raise RuntimeError("PinTools runtime or database is still owned by this checkout")


def cleanup_pintools_resources(
    worktree: Path, directory: Path | None = None, command: str | None = None,
) -> str:
    instances, databases = pintools_resources(worktree, directory)
    for rows, field in ((instances, "id"), (databases, "instance")):
        for row in rows:
            if row.get("uid") != os.getuid():
                raise RuntimeError("PinTools resource owner does not match; teardown refused")
            value = row.get(field)
            if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", value):
                raise RuntimeError("PinTools instance identity is invalid; teardown refused")
    pending = {row["instance"] for row in databases if row.get("state") != "released"}
    active = {row["id"] for row in instances if row.get("status") not in {"stopped", "failed"}}
    targets = pending | active
    if not targets:
        return ""
    executable = command or shutil.which("pintools-local")
    if not executable:
        raise RuntimeError("pintools-local is unavailable; runtime/database teardown did not run")

    def run(action: str, instance: str) -> None:
        # The installed launcher rechecks checkout ownership, runtime/container
        # identities and DB generation tokens. Never print its raw JSON output.
        result = subprocess.run(
            [executable, action, f"--instance:{instance}"], cwd=worktree,
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode:
            raise RuntimeError(
                f"PinTools {action} failed for owned instance {instance} "
                f"(exit {result.returncode}); checkout retained for recovery"
            )

    registered = {row["id"] for row in instances}
    for instance in sorted(targets & registered):
        run("stop", instance)
    for instance in sorted(pending):
        run("release", instance)
    check_pintools_resources(worktree, directory)
    return f"stopped owned runtimes and released {len(pending)} PinTools database slot(s); "


def validate_worktree(watch: Watch) -> tuple[Path, Path]:
    repo, worktree = Path(watch.repo), Path(watch.worktree)
    if (
        worktree.is_symlink() or worktree.resolve() != worktree
        or worktree == repo or not worktree.is_relative_to(Path(watch.managed_root))
        or identity(worktree) != watch.worktree_identity
    ):
        raise RuntimeError("worktree ownership changed")
    records = git(repo, "worktree", "list", "--porcelain", "-z").split("\0\0")
    registered = next((entry.split("\0") for entry in records
                       if entry.startswith(f"worktree {worktree}\0")), None)
    if registered is None:
        raise RuntimeError("worktree is no longer registered in the original repository")
    if any(field == "locked" or field.startswith("locked ") for field in registered):
        raise RuntimeError("worktree is locked")
    if git(worktree, "rev-parse", "--absolute-git-dir") != watch.git_dir:
        raise RuntimeError("worktree Git directory changed")
    return repo, worktree


def remove_worktree(watch: Watch) -> str:
    repo, worktree = validate_worktree(watch)
    check_pintools_resources(worktree)
    for operation in (
        "rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
        "BISECT_START", "sequencer",
    ):
        if (Path(watch.git_dir) / operation).exists():
            raise RuntimeError("a Git operation is still in progress")
    head = git(worktree, "rev-parse", "HEAD")
    if git(worktree, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("uncommitted or untracked files are present")
    exclusions = [f":(glob,exclude)**/{directory}/**" for directory in DISPOSABLE_DIRECTORIES]
    if git(worktree, "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
           "--", ".", *exclusions):
        raise RuntimeError("ignored local files are present outside disposable build/cache directories")
    tips = set(git(worktree, "reflog", "show", "--format=%H", "HEAD").splitlines()) | {head}
    if git(worktree, "rev-list", "--max-count=1", *sorted(tips), "--not", watch.base_head, "--remotes"):
        raise RuntimeError("new commits in HEAD history are not recorded on a remote-tracking branch")
    if git(worktree, "rev-parse", "HEAD") != head:
        raise RuntimeError("HEAD changed during cleanup")
    # Git performs its own final dirty check. Never use --force or remove branches.
    git(repo, "worktree", "remove", str(worktree))
    if worktree.parent.parent == Path(watch.managed_root):
        try:
            worktree.parent.rmdir()
        except OSError:
            pass
    return "removed clean worktree; branches were preserved"


def run_watcher(state: Path) -> int:
    data = json.loads(state.read_text())
    watch = Watch(**{field: data[field] for field in Watch.__dataclass_fields__ if field in data})
    record(state, watch, "watching", "waiting for Codex or its window to exit")
    resource_detail = ""
    try:
        while not ready(watch, panes(watch)):
            time.sleep(0.5)
        # Allow pane processes to finish stopping, then check every pane again.
        time.sleep(1)
        while not ready(watch, panes(watch)):
            time.sleep(0.5)
        if watch.cleanup_pintools:
            _, worktree = validate_worktree(watch)
            record(state, watch, "cleaning", "stopping owned PinTools runtimes and releasing their databases")
            resource_detail = cleanup_pintools_resources(worktree)
            # Runtime shutdown can take time. Recheck panes before deleting files.
            while not ready(watch, panes(watch)):
                time.sleep(0.5)
        detail = remove_worktree(watch)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        detail = resource_detail + str(error)
        record(state, watch, "retained", detail)
        try:
            subprocess.run(
                ["tmux", "-S", watch.socket, "display-message", "-d", "10000",
                 f"Kept Codex worktree {watch.worktree}: {detail}"],
                capture_output=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        return 1
    record(state, watch, "removed", resource_detail + detail)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", required=True, type=Path)
    raise SystemExit(run_watcher(parser.parse_args().watch))
