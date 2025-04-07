# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# If you come from bash you might have to change your $PATH.
export PATH=$HOME/bin:$HOME/.local/bin:/usr/local/bin:$PATH

# Path to your Oh My Zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time Oh My Zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME="powerlevel10k/powerlevel10k"

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment one of the following lines to change the auto-update behavior
# zstyle ':omz:update' mode disabled  # disable automatic updates
# zstyle ':omz:update' mode auto      # update automatically without asking
# zstyle ':omz:update' mode reminder  # just remind me to update when it's time

# Uncomment the following line to change how often to auto-update (in days).
# zstyle ':omz:update' frequency 13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS="true"

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# You can also set it to another string to have that shown instead of the default red dots.
# e.g. COMPLETION_WAITING_DOTS="%F{yellow}waiting...%f"
# Caution: this setting can cause issues with multiline prompts in zsh < 5.7.1 (see #5765)
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(git)

source $ZSH/oh-my-zsh.sh

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='nvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch $(uname -m)"

# Set personal aliases, overriding those provided by Oh My Zsh libs,
# plugins, and themes. Aliases can be placed here, though Oh My Zsh
# users are encouraged to define aliases within a top-level file in
# the $ZSH_CUSTOM folder, with .zsh extension. Examples:
# - $ZSH_CUSTOM/aliases.zsh
# - $ZSH_CUSTOM/macos.zsh
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

ls_colors_pieces=(
    "di=1;34"
    ":"
    "ln=35"
    ":"
    "so=32"
    ":"
    "pi=33"
    ":"
    "ex=31"
    ":"
    "bd=34;46"
    ":"
    "cd=34;43"
    ":"
    "su=30;41"
    ":"
    "sg=30;46"
    ":"
    "tw=30;42"
    ":"
    "ow=30;43"
)
export LS_COLORS=$(printf "%s" "${ls_colors_pieces[@]}")  


auto_virtualenv() {
    command=$(python3 ~/auto-virtualenv/venv_toggle_command.py --command)
    eval $command
}

precmd() {
    auto_virtualenv
}

alias rg="rg --pretty --glob '!tags' --max-columns 300 "
alias rgi="rg --pretty --ignore-case --glob '!tags' --max-columns 300 "

# -r recursive, -n line number -i case insensitive, -s no messages, -I ignore binary, -S follow symlinks
# -o matching only, -h no filename
alias g="egrep -rnisIS --color"
alias gc="egrep -rnsIS --color"

if [[ $(uname) == Darwin ]]; then
    alias l="gls -l -h --color --group-directories-first  --dereference-command-line-symlink-to-dir --dereference-command-line --dereference"
    alias ls="gls -h --color --group-directories-first  --dereference-command-line-symlink-to-dir --dereference-command-line --dereference"
else
    alias l="ls -l -h --color --group-directories-first  --dereference-command-line-symlink-to-dir --dereference-command-line --dereference"
    alias ls="ls -h --color --group-directories-first  --dereference-command-line-symlink-to-dir --dereference-command-line --dereference"
fi

export VIRTUAL_ENV_DISABLE_PROMPT=1

alias aws="aws2"

# otherwise EOL not having a newline prints a `%`
export PROMPT_EOL_MARK=''

# Otherwise it eats the space before the pipe after tab-completing a file name
# https://superuser.com/a/613817/592828
ZLE_REMOVE_SUFFIX_CHARS=""

# For spacedentist spr
export PATH="/home/tanwang/.cargo/bin:$PATH"

# Might have to download the binary directly, since apt has a really old version.
source <(fzf --zsh)

# To put the input field at the top
export FZF_DEFAULT_OPTS=--reverse  # linux
export FZF_CTRL_R_OPTS="--layout=reverse"  # mac

######################## CTRL+W deletion ########################
# Create a new widget.
zle -N backward-kill-space-word
backward-kill-space-word() {
  # Inform the line editor that this widget will kill text.
  zle -f kill
# Set $WORDCHARS for this command only. 
  WORDCHARS='*?_-.[]~=/&;:!#$%^(){}<>' zle .backward-kill-word
}

# See comments above.
zle -N backward-kill-bash-word
backward-kill-bash-word() {
  zle -f kill
  WORDCHARS='' zle .backward-kill-word
}

# Bind the widgets to keys.
bindkey   '^W' backward-kill-space-word
#################################################################

######################## Pinterest Stuff ########################
# Haste
export HASTE_SERVER="https://paste.pinadmin.com/"
export HASTE_SHARE_SERVER="https://paste.pinadmin.com/"
alias haste="haste | sed 's/share\///g'"


if [[ $(hostname) =~ devrestricted-tanwang ]]; then
    export PYENV_ROOT="$HOME/.pyenv"
    [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init - zsh)"

    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
    [ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
fi


# Fix SSH auth socket location so agent forwarding works with tmux
# https://w.pinadmin.com/pages/viewpage.action?pageId=465732721
if [[ $(hostname) =~ devrestricted-tanwang ]]; then
    if test "$SSH_AUTH_SOCK"; then
        if test -z "$TMUX"; then
            if [[ $TERM_PROGRAM != "vscode" ]]; then
                # echo 'Linking ~/.ssh/ssh_auth_sock to $SSH_AUTH_SOCK'
                ln -sf $SSH_AUTH_SOCK ~/.ssh/ssh_auth_sock
            fi
        fi
    fi
fi

#################################################################

