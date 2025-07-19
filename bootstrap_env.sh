#!/bin/bash

REPO_URL="git@github.com:SinOverCos/auto-virtualenv.git"
DEST_DIR="${HOME}/code/auto-virtualenv"

# Check if the destination directory already exists
if [ ! -d "$DEST_DIR" ]; then
  echo "Cloning $REPO_URL into $DEST_DIR..."
  git clone "$REPO_URL" "$DEST_DIR"
else
  echo "Repository already exists at $DEST_DIR. Checking for updates..."
  pushd "$DEST_DIR" > /dev/null
  if [ $? -eq 0 ]; then
    echo "Pulling latest changes in $DEST_DIR..."
    git pull
    popd > /dev/null
  else
    echo "Could not change to $DEST_DIR. Skipping update."
  fi
fi

