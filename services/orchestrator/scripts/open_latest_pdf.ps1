param(
    [string]$Directory = "$env:USERPROFILE\Downloads",
    [string]$Pattern = "fastfix-*.pdf",
    [switch]$SelectInExplorer,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Directory)) {
    Write-Error "Directory not found: $Directory"
}

$latest = Get-ChildItem -LiteralPath $Directory -Filter $Pattern -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $latest) {
    Write-Error "No PDF found in $Directory matching pattern: $Pattern"
}

Write-Host "Latest PDF: $($latest.FullName)"

if (-not $NoOpen) {
    Start-Process $latest.FullName
}

if ($SelectInExplorer) {
    Start-Process explorer.exe "/select,$($latest.FullName)"
}
