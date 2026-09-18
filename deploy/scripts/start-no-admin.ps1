$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

if (!(Test-Path '.venv')) {
  Write-Host 'Creating local virtual environment...'
  python -m venv .venv
}

Write-Host 'Installing runtime dependencies...'
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r services/orchestrator/requirements.txt

Write-Host 'Starting service on 0.0.0.0:8080 ...'
Set-Location services/orchestrator
..\..\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
