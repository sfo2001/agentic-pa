# One-command setup (Windows): create a venv, install the packages, then run the
# guided setup wizard. Safe to re-run.   Usage:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install Python 3.10+ and re-run (or set `$env:PYTHON)."
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtualenv (.venv)..."
    & $py -m venv .venv
}
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Installing packages..."
& $venvPy -m pip install --upgrade pip | Out-Null
# llm-wiki-tools is a required sibling checkout (not on PyPI) — install it editable
# FIRST so it backs the `llm-wiki-tools` dependency of agenda/frontend.
$lwt = if ($env:LLM_WIKI_TOOLS) { $env:LLM_WIKI_TOOLS } else { "../llm-wiki-tools" }
if (-not (Test-Path $lwt)) {
    Write-Error "llm-wiki-tools not found at '$lwt' (a required sibling checkout). Clone it next to this repo (../llm-wiki-tools) or set `$env:LLM_WIKI_TOOLS and re-run."
    exit 1
}
& $venvPy -m pip install -e $lwt -e ./agenda -e ./frontend -e ./presenter
& $venvPy -m pip install -r agenda/requirements-dev.txt -r frontend/requirements-dev.txt

Write-Host ""
& $venvPy -m frontend.setup_wizard
