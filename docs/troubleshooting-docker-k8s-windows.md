# Windows Deployment Troubleshooting (Docker and Kubernetes)

This guide addresses the error shown in Docker Desktop:

- Virtualization support not detected

## Why this happens

Docker Desktop on Windows requires host virtualization plus WSL2/Hyper-V components.
In locked-down enterprise environments, one or more of these are often disabled by policy.

## Fast path to fix

1. Enable CPU virtualization in BIOS/UEFI
- Intel: VT-x and VT-d
- AMD: SVM and IOMMU

2. Enable required Windows features (run as Administrator)
- VirtualMachinePlatform
- Microsoft-Windows-Subsystem-Linux

3. Install/update WSL kernel and set default version
- wsl --install
- wsl --update
- wsl --set-default-version 2

4. Reboot

5. Start Docker Desktop and verify
- docker info

## Admin commands (PowerShell as Administrator)

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All -NoRestart
wsl --install
wsl --update
wsl --set-default-version 2
shutdown /r /t 0
```

## Kubernetes note

A working kubectl client is not enough by itself. You also need an active cluster context.

Check context:

```powershell
kubectl config get-contexts
kubectl config current-context
kubectl get ns
```

If no context exists, request cluster access from platform team and import kubeconfig.

## Enterprise-friendly alternatives when local virtualization is blocked

1. Deploy on internal Linux VM with Docker Engine
- No Docker Desktop required on laptop
- Expose only internal network endpoint

2. Deploy directly to an internal Kubernetes cluster
- Build image in CI or internal build host
- Push to internal registry
- Apply manifests from this repository

3. Keep local development non-containerized
- Run FastAPI directly for development
- Use server/cluster for multi-user access

## What to provide IT for quick resolution

- Docker Desktop error screenshot: virtualization support not detected
- Request BIOS virtualization enablement
- Request WSL2 and VirtualMachinePlatform enablement
- Confirm your user is allowed to run container workloads per corporate policy
