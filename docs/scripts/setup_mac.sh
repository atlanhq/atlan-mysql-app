#!/bin/bash

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to log messages
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Check and install Homebrew
if ! command_exists brew; then
    log "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    log "Homebrew is already installed."
fi

# Check and install pyenv
if ! command_exists pyenv; then
    log "Installing pyenv..."
    brew install pyenv

    # Add pyenv init to shell configuration
    if [[ "$SHELL" == */zsh ]]; then
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
        echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
        echo 'eval "$(pyenv init -)"' >> ~/.zshrc
        source ~/.zshrc
    elif [[ "$SHELL" == */bash ]]; then
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bash_profile
        echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bash_profile
        echo 'eval "$(pyenv init -)"' >> ~/.bash_profile
        source ~/.bash_profile
    else
        log "Unsupported shell. Please add pyenv init manually to your shell configuration."
    fi
else
    log "pyenv is already installed."
fi

# Install Python 3.11.x (latest version) using pyenv
latest_version=$(pyenv install --list | grep -E '^\s*3\.11\.[0-9]+' | tail -n 1 | tr -d '[:space:]')
if ! pyenv versions | grep -q "$latest_version"; then
    log "Installing Python $latest_version..."
    pyenv install "$latest_version"
    pyenv global "$latest_version"
else
    log "Python $latest_version is already installed."
    pyenv global "$latest_version"
fi

# Verify Python version
python_version=$(python --version 2>&1)
if [[ $python_version == *"$latest_version"* ]]; then
    log "Python $latest_version is active: $python_version"
else
    log "Error: Python $latest_version is not active. Current version: $python_version"
    exit 1
fi

# Check and install poetry
if ! command_exists poetry; then
    log "Installing poetry..."
    pip install poetry==1.8.5
else
    log "Poetry is already installed."
fi
