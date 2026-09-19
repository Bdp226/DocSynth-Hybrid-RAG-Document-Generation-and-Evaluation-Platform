<#
.SYNOPSIS
    Runs every DocSynth quality gate locally, in the same order as CI.

.DESCRIPTION
    Windows equivalent of `make check`. Each gate is executed in sequence and
    the script exits with a non-zero code on the first failure, so it can be
    wired into a pre-push hook.

.PARAMETER SkipEval
    Skip the generation-quality evaluation gate (useful for fast inner loops).

.EXAMPLE
    pwsh -File scripts/check.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipEval
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

# Prefer the project virtualenv so the script works without prior activation,
# and so it uses the same pinned tool versions CI does.
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$py = if (Test-Path $venvPython) { $venvPython } else { 'python' }

$failures = @()

function Invoke-Gate {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        $script:failures += $Name
        Write-Host "    FAILED: $Name" -ForegroundColor Red
    }
    else {
        Write-Host "    PASSED: $Name" -ForegroundColor Green
    }
}

try {
    Invoke-Gate -Name 'Lint (ruff check)' -Action { & $py -m ruff check . }
    Invoke-Gate -Name 'Format (ruff format --check)' -Action { & $py -m ruff format --check . }
    Invoke-Gate -Name 'Types (mypy)' -Action { & $py -m mypy }

    # Coverage is measured against the `app` package, which is only importable
    # from the service directory.
    Invoke-Gate -Name 'Tests + coverage (pytest)' -Action {
        Push-Location (Join-Path $repoRoot 'services\orchestrator')
        try { & $py -m pytest tests -q --cov=app --cov-branch --cov-report=term }
        finally { Pop-Location }
    }

    Invoke-Gate -Name 'Security (bandit)' -Action { & $py -m bandit -c pyproject.toml -q -r services/orchestrator/app }

    if (-not $SkipEval) {
        Invoke-Gate -Name 'Quality gate (eval)' -Action { & $py pipelines/eval/run_eval.py --mode mock --gate }
    }

    Write-Host ""
    if ($failures.Count -gt 0) {
        Write-Host "Quality gates failed:" -ForegroundColor Red
        $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        exit 1
    }

    Write-Host "All quality gates passed." -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
