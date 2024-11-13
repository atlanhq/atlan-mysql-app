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

# Install Python 3.11 using pyenv
if ! pyenv versions | grep -q "3.11.0"; then
    log "Installing Python 3.11.0..."
    pyenv install 3.11.0
    pyenv global 3.11.0
else
    log "Python 3.11.0 is already installed."
fi

# Verify Python version
python_version=$(python --version 2>&1)
if [[ $python_version == *"3.11"* ]]; then
    log "Python 3.11 is active: $python_version"
else
    log "Error: Python 3.11 is not active. Current version: $python_version"
    exit 1
fi

# Check and install poetry
if ! command_exists poetry; then
    log "Installing poetry..."
    curl -sSL https://install.python-poetry.org | python -
else
    log "Poetry is already installed."
fi
