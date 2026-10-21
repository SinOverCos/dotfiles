# Dotfiles

## Codex preferences

Keep personal Codex preferences shared between the Mac and devapps. The
preference helper requires Python 3.11 or newer. From this repository root,
edit the tracked preferences and apply them:

```bash
${EDITOR:-vi} codex/config.toml
python3 scripts/sync_codex_config.py
```

Symlink setup and new interactive shells also apply the shared preferences.
Existing Codex sessions retain their loaded settings. Machine-specific MCP
routing, authentication, hooks, plugins, and project trust remain local; the
home configuration stays a regular file that the managed catalog can update.
When preferences change, the helper rewrites TOML formatting and saves the
original configuration beside it in a private backup. Unchanged files are
left byte-for-byte intact.

After changing preferences through Codex, capture them before opening a new
shell, which would reapply the tracked version:

```bash
python3 scripts/sync_codex_config.py --capture
```

Capture includes only the portable preference allowlist. Review the resulting
Git diff before syncing dotfiles to other machines. If applying preferences
fails, the helper leaves the local configuration in place and prints the
error; correct invalid TOML or unexpected local types before retrying.

## Codex worktree windows

Press `Ctrl-a`, then `Ctrl-w` for Codex, or `Ctrl-a`, then `Ctrl-c` for Claude
Code. Press `Ctrl-q` to close the whole window immediately, including both
panes, without a confirmation prompt.

Both panes appear before Git starts. After refreshing the base checkout, the
launcher creates a detached worktree with root configuration, instructions,
and agent skills first. The agent opens on the right immediately; you can
type at its input prompt while the rest of the source files load in the
background. Keys typed during the initial starting screen are discarded.
The left pane shows progress and becomes a shell when loading finishes. The agent
stays in the same process and directory, preserving unfinished drafts.

Both agents receive startup instructions to check readiness before reading,
searching, or changing repository files. Conversation and typing can begin
while loading continues. Loading failures stay visible on the left and are
reported by the readiness check. Early file changes are preserved by Git's
sparse-checkout expansion. The launcher never force-resets a live worktree.
There is no spare worktree or prewarming service.

New panes skip PinTools' automatic dependency installation using
`PINTOOLS_READ_ONLY=1`. Files remain editable, and explicit dependency installs
still work. Install only the packages needed for the task. Dependencies and
generated files stay separate in each worktree.

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
Cleanup also waits for background loading to finish. If the loader stops
unexpectedly, cleanup retains the checkout for inspection. For newly opened
windows, the detached watcher stops the worktree's owned PinTools instances
and wipes/releases their disposable databases before checking whether the
source checkout can be removed. This runs asynchronously after the panes
leave the checkout, so Ctrl-q returns immediately. Dirty source or unpushed
commits still keep the worktree, even after app/database cleanup succeeds.
Teardown failures retain the checkout and explain the failed step in its
watcher state. Other checkouts' instances and data are left alone. Older
already-running watchers keep their original policy. The watcher never
force-removes a worktree.

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
