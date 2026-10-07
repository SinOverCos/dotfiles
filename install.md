# Things to Install

## Mac

iTerm

Homebrew
* Amphetamine https://apps.apple.com/us/app/amphetamine/id937984704?mt=12
* Bartender https://www.macbartender.com/
* Clipy https://github.com/Clipy/Clipy
* coreutils `brew install coreutils`
* fzf https://github.com/junegunn/fzf?tab=readme-ov-file#using-homebrew
* Karabinder-Elements https://karabiner-elements.pqrs.org/
* MonitorControl https://github.com/MonitorControl/MonitorControl?tab=readme-ov-file#download
* oh-my-zsh https://ohmyz.sh/#install
  * p10k: https://github.com/romkatv/powerlevel10k
* Rectangle (Spectacle) https://rectangleapp.com/
* Tmux `brew install tmux`

## Linux

### tmux-resurrect

The shared `.tmux.conf` loads Resurrect from `~/code/tmux-resurrect`, with
`~` expanded on each machine. Run this on the devapp (and on data-devapp if
you use tmux there):

```sh
mkdir -p "$HOME/code"
git clone https://github.com/tmux-plugins/tmux-resurrect.git "$HOME/code/tmux-resurrect"
tmux source-file "$HOME/.tmux.conf"
```

If the checkout already exists, run `git -C ~/code/tmux-resurrect pull --ff-only`
instead of cloning. With this config's `Ctrl-a` prefix, save a
session with `Ctrl-a Ctrl-s` and restore one with `Ctrl-a Ctrl-r`.
