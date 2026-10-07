#!/usr/bin/env python3
"""Sync the Mac, devapp, and data-devapp dotfiles checkouts through Git."""

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys


REPO = Path(__file__).resolve().parent
HOSTS = ("devapp", "data-devapp")
INCOMING_REF = "refs/dotfiles-sync/incoming"
SSH_OPTIONS = (
    "-o", "RemoteCommand=none",
    "-o", "RequestTTY=no",
    "-o", "ConnectTimeout=10",
    "-o", "ConnectionAttempts=1",
    "-o", "ControlMaster=auto",
    "-o", f"ControlPath={Path.home() / '.ssh' / 'dotfiles-sync-%C'}",
    "-o", "ControlPersist=10m",
)
GIT_SSH_COMMAND = shlex.join(("ssh", *SSH_OPTIONS))

REMOTE_CHECK = r"""
set -eu
repo="$HOME/code/dotfiles"
test -d "$repo" || { echo "Missing checkout: $repo" >&2; exit 1; }
cd "$repo"
branch=$(git -C "$repo" symbolic-ref --quiet --short HEAD) || {
    echo "Checkout is not on a branch: $repo" >&2; exit 1;
}
test "$branch" = "$1" || {
    echo "Expected branch $1, found $branch in $repo" >&2; exit 1;
}
for state in MERGE_HEAD rebase-merge rebase-apply CHERRY_PICK_HEAD REVERT_HEAD; do
    path=$(git -C "$repo" rev-parse --git-path "$state")
    test ! -e "$path" || {
        echo "Finish the in-progress Git operation in $repo first" >&2; exit 1;
    }
done
test -z "$(git -C "$repo" ls-files -u)" || {
    echo "Resolve unmerged files in $repo first" >&2; exit 1;
}
git -C "$repo" rev-parse HEAD
"""

REMOTE_STATUS = r"""
set -eu
repo="$HOME/code/dotfiles"
git -C "$repo" status --short
"""

REMOTE_SNAPSHOT = r"""
set -eu
repo="$HOME/code/dotfiles"
cd "$repo"
branch=$(git -C "$repo" symbolic-ref --quiet --short HEAD)
test "$branch" = "$1" || {
    echo "Branch changed on remote: $branch" >&2; exit 1;
}
for state in MERGE_HEAD rebase-merge rebase-apply CHERRY_PICK_HEAD REVERT_HEAD; do
    path=$(git -C "$repo" rev-parse --git-path "$state")
    test ! -e "$path" || {
        echo "Finish the in-progress Git operation in $repo first" >&2; exit 1;
    }
done
test -z "$(git -C "$repo" ls-files -u)" || {
    echo "Resolve unmerged files in $repo first" >&2; exit 1;
}
git -C "$repo" add -A
if ! git -C "$repo" diff --cached --quiet; then
    git -C "$repo" commit -m "$2" >&2
fi
git -C "$repo" rev-parse HEAD
"""

REMOTE_APPLY = r"""
set -eu
repo="$HOME/code/dotfiles"
branch=$(git -C "$repo" symbolic-ref --quiet --short HEAD)
test "$branch" = "$1" || {
    echo "Branch changed on remote: $branch" >&2; exit 1;
}
actual=$(git -C "$repo" rev-parse HEAD)
test "$actual" = "$2" || {
    echo "Remote gained new commits; rerun sync" >&2; exit 1;
}
git -C "$repo" diff --quiet || {
    echo "Remote has new edits; rerun sync" >&2; exit 1;
}
git -C "$repo" diff --cached --quiet || {
    echo "Remote has new staged edits; rerun sync" >&2; exit 1;
}
incoming=$(git -C "$repo" rev-parse refs/dotfiles-sync/incoming)
test "$incoming" = "$3" || {
    echo "Incoming ref changed on remote; rerun sync" >&2; exit 1;
}
git -C "$repo" merge --ff-only --no-edit "$incoming" >&2
git -C "$repo" update-ref -d refs/dotfiles-sync/incoming "$incoming"
git -C "$repo" rev-parse HEAD
"""


class SyncError(Exception):
    pass


def run(command, *, cwd=None, env=None, input_text=None):
    result = subprocess.run(
        command,
        cwd=cwd or REPO,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SyncError(f"{shlex.join(command)} failed: {detail}")
    return result.stdout.rstrip("\n"), result.stderr.rstrip("\n")


def git(*args, env=None):
    return run(("git", *args), env=env)[0]


def remote(host, script, *args):
    remote_command = "sh -s -- " + " ".join(shlex.quote(arg) for arg in args)
    return run(("ssh", *SSH_OPTIONS, host, remote_command), input_text=script)


def remote_git_env():
    return {**os.environ, "GIT_SSH_COMMAND": GIT_SSH_COMMAND}


def remote_git_url(host):
    # Git interprets this path relative to the remote user's home directory.
    return f"{host}:code/dotfiles"


def local_branch():
    top = Path(git("rev-parse", "--show-toplevel")).resolve()
    if top != REPO.resolve():
        raise SyncError(f"Expected checkout at {REPO}, found {top}")
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        raise SyncError("The Mac checkout is detached from a branch")
    return branch


def check_local_git_operation():
    for state in (
        "MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"
    ):
        path = git("rev-parse", "--git-path", state)
        if (REPO / path).exists():
            raise SyncError("Finish the in-progress Git operation on the Mac first")
    if git("ls-files", "-u"):
        raise SyncError("Resolve unmerged files on the Mac first")


def show_status(branch):
    print(f"Mac ({branch}):")
    print(git("status", "--short") or "  clean")
    for host in HOSTS:
        remote_head, _ = remote(host, REMOTE_CHECK, branch)
        advertised = git(
            "ls-remote", "--exit-code", remote_git_url(host),
            f"refs/heads/{branch}", env=remote_git_env(),
        ).split()[0]
        if advertised != remote_head:
            raise SyncError(f"{host} changed during the status check; rerun")
        status, _ = remote(host, REMOTE_STATUS)
        print(f"{host} ({branch}):")
        print(status or "  clean")


def snapshot_mac(branch):
    if local_branch() != branch:
        raise SyncError("The Mac branch changed during sync; rerun")
    check_local_git_operation()
    git("add", "-A")
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", "Sync dotfiles from Mac")
        print("Committed Mac edits")
    return git("rev-parse", "HEAD")


def snapshot_host(host, branch):
    head, messages = remote(
        host, REMOTE_SNAPSHOT, branch, f"Sync dotfiles from {host}"
    )
    if messages:
        print(messages)
    print(f"Snapshotted {host}: {head[:12]}")
    return head


def merge_in_progress():
    path = git("rev-parse", "--git-path", "MERGE_HEAD")
    return (REPO / path).exists()


def codex_command():
    override = os.environ.get("DOTFILES_SYNC_CODEX_COMMAND")
    if override is None:
        # The working copy may contain merge markers in .zshrc. HEAD is the
        # Mac's committed version from just before the failed merge.
        zshrc = git("show", "HEAD:.zshrc")
        alias, _ = run(
            (
                "zsh", "-f", "-c",
                'source /dev/stdin >/dev/null 2>&1; '
                '[[ -n ${aliases[cx]-} ]] || exit 2; '
                'print -r -- "${aliases[cx]}"',
            ),
            input_text=zshrc,
        )
        command = shlex.split(alias)
    else:
        command = shlex.split(override)
    if not command:
        raise SyncError("No Codex command is configured")
    return command


def launch_codex(label):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SyncError(
            f"Merge conflict with {label}, but no interactive terminal is "
            "available. Resolve and commit the merge on the Mac, then rerun sync"
        )
    command = codex_command()
    prompt = (
        f"A Git merge of {label} into this dotfiles checkout has conflicts. "
        "Inspect git status and resolve every conflict, preserving the intended "
        "changes from both sides. Ask me interactively when intent is ambiguous. "
        "Review auto-merged files too for accidental duplicate settings. Stage "
        "all resolved files with git add and run git diff --cached --check. "
        "Do not commit, abort the merge, switch branches, push, or edit "
        "unrelated files. When everything is resolved and staged, tell me to "
        "exit this Codex session; the sync script will finish the merge and "
        "continue."
    )
    print(
        f"Opening interactive Codex for the {label} merge with "
        f"{shlex.join(command)}...",
        flush=True,
    )
    try:
        result = subprocess.run((*command, prompt), cwd=REPO)
    except OSError as exc:
        raise SyncError(f"Could not launch Codex: {exc}") from exc
    if result.returncode:
        raise SyncError(
            f"Codex exited with status {result.returncode}; the merge remains "
            "on the Mac for manual resolution"
        )


def is_ancestor(revision):
    result = subprocess.run(
        ("git", "merge-base", "--is-ancestor", revision, "HEAD"),
        cwd=REPO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def resolve_with_codex(label, revision, branch):
    launch_codex(label)
    if local_branch() != branch:
        raise SyncError("Codex changed the Mac branch; stop and inspect Git state")
    if git("ls-files", "-u"):
        raise SyncError(
            "Codex left unresolved conflicts; resolve, stage, and commit "
            "the merge on the Mac before rerunning sync"
        )
    if merge_in_progress():
        if git("diff", "--name-only") or git(
            "ls-files", "--others", "--exclude-standard"
        ):
            raise SyncError(
                "Codex left unstaged files; stage and commit the merge on "
                "the Mac before rerunning sync"
            )
        git("diff", "--cached", "--check")
        git("commit", "--no-edit")
    if not is_ancestor(revision):
        raise SyncError(f"The {label} merge was not completed on the Mac")
    if git("diff", "--name-only") or git("diff", "--cached", "--name-only"):
        raise SyncError("Codex left new Mac edits after resolving the merge")


def merge_ref(label, revision):
    before = git("rev-parse", "HEAD")
    if before == revision:
        print(f"Already current with {label}")
        return
    branch = local_branch()
    try:
        git("merge", "--no-edit", revision)
    except SyncError:
        if not merge_in_progress() or not git("ls-files", "-u"):
            raise
        resolve_with_codex(label, revision, branch)
    print(f"Merged {label}")


def require_clean_tracked_mac():
    if git("diff", "--name-only") or git("diff", "--cached", "--name-only"):
        raise SyncError("New Mac edits appeared during sync; rerun to include them")


def sync():
    if sys.platform != "darwin":
        raise SyncError("Run sync from the Mac, outside the devapp sandboxes")
    branch = local_branch()
    check_local_git_operation()

    # Check both machines before making a commit anywhere.
    show_status(branch)
    git("fetch", "--no-tags", "origin")
    snapshot_mac(branch)
    remote_heads = {host: snapshot_host(host, branch) for host in HOSTS}

    if local_branch() != branch:
        raise SyncError("The Mac branch changed during sync; rerun")
    merge_ref("origin", git("rev-parse", f"refs/remotes/origin/{branch}"))
    for host in HOSTS:
        if local_branch() != branch:
            raise SyncError("The Mac branch changed during sync; rerun")
        git(
            "fetch", "--no-tags", remote_git_url(host), f"refs/heads/{branch}",
            env=remote_git_env(),
        )
        fetched = git("rev-parse", "FETCH_HEAD")
        if fetched != remote_heads[host]:
            raise SyncError(f"{host} changed after its snapshot; rerun sync")
        merge_ref(host, fetched)

    require_clean_tracked_mac()
    if local_branch() != branch:
        raise SyncError("The Mac branch changed during sync; rerun")
    head = git("rev-parse", "HEAD")
    git("push", "origin", f"{head}:refs/heads/{branch}")
    print(f"Pushed origin/{branch}: {head[:12]}")

    for host in HOSTS:
        git(
            "push", remote_git_url(host), f"{head}:{INCOMING_REF}",
            env=remote_git_env(),
        )
        updated, messages = remote(
            host, REMOTE_APPLY, branch, remote_heads[host], head
        )
        if messages:
            print(messages)
        if updated != head:
            raise SyncError(f"{host} ended at {updated}, expected {head}")
        print(f"Updated {host}: {head[:12]}")
    print("All tracked and nonignored new files are synced across all three checkouts")


def resume():
    if sys.platform != "darwin":
        raise SyncError("Run resume from the Mac, outside the devapp sandboxes")
    if not merge_in_progress():
        raise SyncError("No merge is in progress on the Mac; run sync instead")
    branch = local_branch()
    revision = git("rev-parse", "MERGE_HEAD")
    resolve_with_codex("current merge", revision, branch)
    sync()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "sync", "resume"))
    args = parser.parse_args()
    try:
        if args.command == "status":
            show_status(local_branch())
        elif args.command == "resume":
            resume()
        else:
            sync()
    except SyncError as exc:
        print(f"Sync stopped: {exc}", file=sys.stderr)
        if args.command in ("sync", "resume"):
            print(
                "If Git left a merge in progress on the Mac, run "
                "python3 sync_dotfiles.py resume from a regular Mac Terminal.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
