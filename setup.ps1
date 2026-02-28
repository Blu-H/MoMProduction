$ErrorActionPreference = "Stop"

############################################
# CONFIG
############################################

$RepoUrl = "https://github.com/Blu-H/MoMProduction.git"
$RepoDir = "$HOME\MoMProduction"
$RepoBranch = "dev"
$PythonVersionRequired = "3.12"

############################################
# ENSURE WINGET INSTALLED
############################################

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "Installing winget..."
    Add-AppxPackage -Path "https://aka.ms/getwinget"
}

############################################
# ENSURE PYTHON 3.12 INSTALLED
############################################

$pythonInstalled = $false

try {
    $pyVersion = py -3.12 --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        $pythonInstalled = $true
    }
} catch {}

if (-not $pythonInstalled) {
    Write-Host "Installing Python 3.12..."
    winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
} else {
    Write-Host "Python 3.12 already installed."
}

############################################
# ENSURE GIT INSTALLED
############################################

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Git..."
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
} else {
    Write-Host "Git already installed."
}

############################################
# CLONE OR UPDATE REPOSITORY
############################################

if (-not (Test-Path "$RepoDir\.git")) {
    Write-Host "Cloning repository..."
    git clone --branch $RepoBranch --single-branch --depth 1 $RepoUrl $RepoDir
} else {
    Write-Host "Repository already exists. Skipping clone."
}

############################################
# ENSURE UV INSTALLED (LOCAL INSTALLER)
############################################

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv from local installer..."
    & "$RepoDir\installers\uv-installer.ps1"
} else {
    Write-Host "uv already installed."
}

############################################
# CREATE VENV IF NOT EXISTS
############################################

Set-Location $RepoDir

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment with Python 3.12..."
    uv venv --python 3.12
} else {
    Write-Host ".venv already exists."
}

############################################
# ACTIVATE VENV
############################################

. .\.venv\Scripts\Activate.ps1

############################################
# OPTIONAL SSL FIX
############################################

$env:SSL_CERT_FILE = "$PWD\.venv\Lib\site-packages\certifi\cacert.pem"
$env:CURL_CA_BUNDLE = $env:SSL_CERT_FILE
$env:REQUESTS_CA_BUNDLE = $env:SSL_CERT_FILE

############################################
# INSTALL REQUIRED WHEELS (IDEMPOTENT)
############################################

if (-not (Get-Module -ListAvailable -Name osgeo)) {
    Write-Host "Installing GDAL wheel..."
    uv pip install ./installers/gdal-3.11.4-cp312-cp312-win_amd64.whl
}

if (-not (Get-Module -ListAvailable -Name pyproj)) {
    Write-Host "Installing pyproj wheel..."
    uv pip install ./installers/pyproj-3.7.2-cp312-cp312-win_amd64.whl
}

############################################
# SET PROJ_LIB
############################################

$env:PROJ_LIB = "$PWD\.venv\Lib\site-packages\pyproj\proj_dir\share\proj"

############################################
# INSTALL PROJECT IF NOT INSTALLED
############################################

$projectInstalled = pip show MoMProduction 2>$null
if (-not $projectInstalled) {
    Write-Host "Installing project..."
    uv pip install .
} else {
    Write-Host "Project already installed."
}

############################################
# RUN INITIALIZATION
############################################

Write-Host "Running initialize.py..."
python initialize.py

############################################
# DONE
############################################

Write-Host ""
Write-Host "======================================"
Write-Host "Setup complete."
Write-Host "======================================"