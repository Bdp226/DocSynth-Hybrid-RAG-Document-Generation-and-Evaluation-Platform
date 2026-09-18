# No-Admin Runbook (No Docker, No Kubernetes)

Use this mode when you do not have admin rights for BIOS, WSL, Docker, or Hyper-V.

## What this gives you

- Full UI and API on your machine
- Compose workflow with text + image inputs
- PDF and DOCX generation
- Internal network sharing via your laptop IP

## Step 1: Start service without admin

Run:

powershell -ExecutionPolicy Bypass -File deploy/scripts/start-no-admin.ps1

## Step 2: Get access URLs

Open a second terminal and run:

powershell -ExecutionPolicy Bypass -File deploy/scripts/show-access-urls.ps1

## Step 3: Share with users on same network

Share the URL shown as:

http://YOUR-IP:8080/ui/

## Common limitation

If other users cannot connect, your corporate firewall policy is blocking inbound port 8080.
You will need IT help to allow inbound access for this process or host the app on an internal VM.

## Enterprise recommendation without local admin

Use a centrally managed internal VM or cluster where IT handles container runtime and network policy.
Develop locally with this no-admin mode; deploy centrally through CI/CD.
