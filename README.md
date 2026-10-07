# Dotfiles

The Mac, `devapp`, and `data-devapp` each have a checkout at
`~/code/dotfiles`. Run the sync helper from an ordinary Mac Terminal session,
outside the coding sandbox:

```bash
cd ~/code/dotfiles
python3 sync_dotfiles.py status  # inspect all three working trees
python3 sync_dotfiles.py sync    # commit, merge, publish, and update each checkout
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
checkout and nothing new is pushed to GitHub. Resolve the conflict, `git add`
the files, `git commit`, then rerun `python3 sync_dotfiles.py sync`. If a devapp
changes during the run, the helper stops before overwriting it. Rerunning
includes its new changes. Existing home dotfile symlinks point at their local
checkout.
