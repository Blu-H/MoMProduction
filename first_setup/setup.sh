#!/usr/bin/env bash

set -e  # Exit on error
set -o pipefail

############################
# CONFIG
############################

REPO_URL="https://github.com/KatKatKateryna/MoMProduction.git"
REPO_DIR="$HOME/MoMProduction"
REPO_BRANCH="main"
if command -v conda >/dev/null 2>&1; then
    CONDA_DIR="$(conda info --base)"
else
    CONDA_DIR="$HOME/miniconda3"
fi
CONDA_ENV_NAME="myenv"
MINICONDA_INSTALLER="Miniconda3-latest-Linux-x86_64.sh"
MINICONDA_URL="https://repo.anaconda.com/miniconda/$MINICONDA_INSTALLER"

############################
# CI DETECTION
############################

IS_GITHUB_ACTIONS=false
if [ "$GITHUB_ACTIONS" = "true" ]; then
    IS_GITHUB_ACTIONS=true
    echo "Running inside GitHub Actions - skipping system install and repo setup."
fi

############################
# SYSTEM UPDATE
############################
if [ "$IS_GITHUB_ACTIONS" = false ]; then
    echo "Updating system packages..."
    sudo apt update -y
    sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y

    echo "Installing required system packages..."
    sudo DEBIAN_FRONTEND=noninteractive apt install -y \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        curl \
        git \
        wget
else
    echo "Skipping system package installation in GitHub Actions."
fi

############################
# REPOSITORY SETUP
############################
if [ "$IS_GITHUB_ACTIONS" = false ]; then
    echo "Setting up repository..."

    if [ ! -d "$REPO_DIR/.git" ]; then
        echo "Cloning repository..."
        git clone --branch "$REPO_BRANCH" --single-branch --depth 1 "$REPO_URL" "$REPO_DIR"
    else
        echo "Repository exists. Resetting to origin/$REPO_BRANCH..."
        cd "$REPO_DIR"
        git fetch origin
        git reset --hard "origin/$REPO_BRANCH"
        cd "$HOME"
    fi
else
    echo "Skipping repository setup in GitHub Actions."
    REPO_DIR="$(pwd)"
fi

############################
# MINICONDA INSTALL
############################
if [ ! -d "$CONDA_DIR" ]; then
    echo "Miniconda not found. Installing..."

    cd "$HOME"

    if [ ! -f "$MINICONDA_INSTALLER" ]; then
        wget "$MINICONDA_URL"
    fi

    bash "$MINICONDA_INSTALLER" -b -p "$CONDA_DIR"

fi

# Initialize conda for bash (safe to re-run)
echo "Conda DIR: $CONDA_DIR"
"$CONDA_DIR/bin/conda" init bash || true

# Source conda
source "$CONDA_DIR/etc/profile.d/conda.sh"
"$CONDA_DIR/bin/conda" tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
"$CONDA_DIR/bin/conda" tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

############################
# CONDA CONFIG
############################

echo "Configuring conda..."

conda config --add channels conda-forge || true
conda config --set channel_priority strict

############################
# CREATE OR UPDATE ENV
############################

cd "$REPO_DIR"

if conda env list | grep -q "^$CONDA_ENV_NAME "; then
    echo "Environment exists. Updating..."
    conda env update -n "$CONDA_ENV_NAME" -f environment.yml --prune
else
    echo "Creating environment..."
    conda env create -n "$CONDA_ENV_NAME" -f environment.yml
fi

############################
# ACTIVATE ENV
############################

conda activate "$CONDA_ENV_NAME"

echo "Installing libgdal-hdf4 in environment..."
conda install -c conda-forge libgdal-hdf4 -y

############################
# RUN INITIALIZE.PY
############################

python initialize.py

############################
# TODO: replace env vars
############################

echo ""
echo "======================================"
echo "Setup complete."
echo "To activate environment in new shells:"
echo "    conda activate $CONDA_ENV_NAME"
echo "======================================"