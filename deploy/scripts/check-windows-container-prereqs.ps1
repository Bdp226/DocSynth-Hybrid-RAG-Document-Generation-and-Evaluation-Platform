$ErrorActionPreference = 'Continue'

Write-Host '=== Windows Container Prerequisite Check ==='
Write-Host "User: $env:USERNAME"
Write-Host "Host: $env:COMPUTERNAME"
Write-Host ''

Write-Host '1) Hypervisor and virtualization signals'
Get-ComputerInfo |
  Select-Object HyperVisorPresent,
                HyperVRequirementDataExecutionPreventionAvailable,
                HyperVRequirementSecondLevelAddressTranslation,
                HyperVRequirementVirtualizationFirmwareEnabled,
                HyperVRequirementVMMonitorModeExtensions |
  Format-List

Write-Host '2) WSL status'
try {
  wsl --status
} catch {
  Write-Host 'WSL status unavailable or WSL not installed.'
}

Write-Host ''
Write-Host '3) Docker Desktop binaries'
$dockerDesktop = "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
$dockerCli = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
Write-Host "Docker Desktop app: $dockerDesktop"
Write-Host "Exists: $(Test-Path $dockerDesktop)"
Write-Host "Docker CLI: $dockerCli"
Write-Host "Exists: $(Test-Path $dockerCli)"

if (Test-Path $dockerCli) {
  Write-Host ''
  Write-Host '4) Docker client/server check'
  try {
    & $dockerCli --version
    & $dockerCli info --format '{{.ServerVersion}}'
  } catch {
    Write-Host 'Docker engine not reachable.'
  }
}

Write-Host ''
Write-Host '5) Kubernetes context check'
$kubectl = "$env:USERPROFILE\bin\kubectl.exe"
if (Test-Path $kubectl) {
  try {
    & $kubectl version --client
    & $kubectl config get-contexts
    & $kubectl config current-context
  } catch {
    Write-Host 'kubectl installed, but context or cluster access is missing.'
  }
} else {
  Write-Host 'kubectl not found at expected user path.'
}

Write-Host ''
Write-Host '=== Completed ==='
