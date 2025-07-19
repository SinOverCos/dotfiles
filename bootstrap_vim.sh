set -euxo pipefail

VIM_DIR="$HOME/.vim"
REPO_URL="git@github.com:SinOverCos/dotvim.git"

if [ -d "$VIM_DIR" ]; then
  echo "Directory $VIM_DIR already exists. Pulling latest changes and updating submodules..."
  git -C "$VIM_DIR" pull
else
  echo "Cloning $REPO_URL into $VIM_DIR..."
  git clone "$REPO_URL" "$VIM_DIR"
fi

if [ -d "$VIM_DIR" ]; then
  echo "Updating Git submodules in $VIM_DIR..."
  git -C "$VIM_DIR" submodule update --init --recursive
else
  echo "Could not update submodules: $VIM_DIR does not exist."
fi

