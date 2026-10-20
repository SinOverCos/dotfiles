# Dotfiles

## Codex worktree windows

Press `Ctrl-a`, then `Ctrl-w` to open a Codex worktree window with a shell
on the left. Press `Ctrl-q` to close the whole window immediately, including
both panes, without a confirmation prompt.

The launcher refreshes the base checkout with a fast-forward update, creates
its own detached worktree, and starts Codex there. It does not guess which
worktree belongs to the window from other sessions' filesystem changes.
Each new window starts a detached cleanup watcher on the host, outside the
agent sandbox and the window's panes. This starts automatically on macOS
and Linux, with no separate service setup. It requires Python 3.9 or newer,
Git, tmux, zsh, and the existing `cx` command on that host. It survives closing
the window. If Codex exits normally, cleanup waits for the left shell and
any other panes in that tmux server to leave the worktree. Closing the window also triggers
cleanup. The watcher removes only its own clean, unlocked worktree with no
new commits missing from remote-tracking branches. It preserves branches,
uncommitted and untracked files, unpushed commits, and unfinished Git
operations. Ignored local files also prevent removal, except recognized
generated dependency, build, and cache directories.
It never force-removes a worktree.

To find the current window's watcher state, run
`tmux show-options -w -v @cx_cleanup_state`. State and logs are
stored under `/Users/tanwang/.local/state/tmux-cx-worktree/` on the Mac or
`/home/tanwang/.local/state/tmux-cx-worktree/` on a devapp, unless
`XDG_STATE_HOME` is configured. If cleanup retains a worktree, its state file
and log explain why. Watchers cover windows opened with the updated launcher;
they do not adopt existing worktrees or resume after a host reboot.

After committing and pushing the dotfiles changes, update each other
machine's dotfiles checkout with a rebase, then reload tmux. From that
machine's dotfiles repository root, run:

```bash
git pull --rebase
tmux source-file .tmux.conf
```

Reload tmux on the Mac too. Both launcher scripts must accompany the tmux
configuration. Start a new worktree window after reloading.

The Mac, `devapp`, and `data-devapp` each have a checkout at
`~/code/dotfiles`. Run the sync helper from an ordinary Mac Terminal session,
outside the coding sandbox:

```bash
cd ~/code/dotfiles
python3 sync_dotfiles.py status  # inspect all three working trees
python3 sync_dotfiles.py sync    # commit, merge, publish, and update each checkout
python3 sync_dotfiles.py resume  # reopen Codex for an unfinished Mac merge
```

The Mac is the hub. `sync` commits tracked edits and new files that Git does
not ignore on each machine, fetches both devapp branches over SSH, merges them
with the Mac and GitHub `origin`, pushes the result to `origin`, then
fast-forwards both devapps. Commits already made on either devapp are included
too. The devapps never need to push to GitHub. The helper expands
`$HOME/code/dotfiles` on each devapp, so differing home directories work. It
also overrides the SSH aliases' forced command and TTY settings. You can run
`sync` again later; a run with no new edits creates no commits.

Untracked files appear as `??` in `status` and are included by `sync`. Add
files you want to exclude to `.gitignore` before syncing.

If edits conflict, the script opens interactive Codex in the same Mac Terminal
using the current `cx` alias from this repo's `.zshrc`, including its model and
flags. You can give Codex input. After it stages the resolutions, exit Codex;
the script checks that the conflict is resolved, commits the merge, and
continues. Set `DOTFILES_SYNC_CODEX_COMMAND` to override the alias if needed.
If Codex exits without resolving everything, Git leaves the merge in the Mac
checkout and nothing new is pushed to GitHub. Run `python3 sync_dotfiles.py
resume` to reopen Codex and continue the sync, or resolve and commit the merge
manually before running `sync` again. The helper reads the committed Mac
`.zshrc` for `cx`, so conflict markers in the working copy do not prevent Codex
from starting. If a devapp changes during the run, the helper stops before
overwriting it. Rerunning includes its new changes. Existing home dotfile
symlinks point at their local checkout.

## Personal agent plugins

Plugin source and the installer live in `~/code/tanwang`. The symlink setup
and interactive shell startup run `python3 ~/code/tanwang/bootstrap.py --auto`
when the personal checkout exists. Bootstrap installs default plugins into
available Claude Code and Codex CLIs and skips unchanged installations.

On a new machine, clone the personal repo and run:

```bash
python3 ~/code/tanwang/bootstrap.py
```

Start new agent sessions inside tmux. Open `/hooks` in Codex to review and
trust newly installed hooks. See `~/code/tanwang/docs/bootstrap.md` for
updates, adding plugins, and troubleshooting.
