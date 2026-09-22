param(
    [int]$Port = 8090,
    [string]$SourcePpt = "Sandbox environment.pptx",
    [string]$Pattern = "fastfix-*.pdf",
    [string]$OutputDir = "$env:USERPROFILE\Downloads",
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OrchestratorDir = Resolve-Path (Join-Path $ScriptDir "..")
$RepoRoot = Resolve-Path (Join-Path $OrchestratorDir "..\..")
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$RegenScript = Join-Path $ScriptDir "regenerate_from_ppt_fixed.py"
$OpenScript = Join-Path $ScriptDir "open_latest_pdf.ps1"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Error "Python executable not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $RegenScript)) {
    Write-Error "Regeneration script not found: $RegenScript"
}
if (-not (Test-Path -LiteralPath $OpenScript)) {
    Write-Error "Open script not found: $OpenScript"
}

Push-Location $OrchestratorDir
try {
    $env:PYTHONPATH = "."

    & $PythonExe $RegenScript --port $Port --source-ppt $SourcePpt --output-dir $OutputDir --formats pdf
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    if ($NoOpen) {
        & $OpenScript -Directory $OutputDir -Pattern $Pattern -NoOpen
    }
    else {
        & $OpenScript -Directory $OutputDir -Pattern $Pattern -SelectInExplorer
    }
}
finally {
    Pop-Location
}
