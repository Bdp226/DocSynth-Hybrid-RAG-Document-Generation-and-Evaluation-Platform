# Kubernetes Notes

## Build and load image (example)

```powershell
cd services/orchestrator
docker build -t doc-optimizer-orchestrator:latest .
```

If your cluster is remote, push to an internal registry and update image name in `orchestrator-deployment.yaml`.

## Deploy

```powershell
kubectl apply -f namespace.yaml
kubectl apply -f vector-db-deployment.yaml
kubectl apply -f orchestrator-deployment.yaml
```

## Deploy advanced profile

```powershell
kubectl apply -f advanced/configmap.yaml
kubectl apply -f advanced/llm-deployment.yaml
kubectl apply -f advanced/networkpolicy.yaml
kubectl apply -f advanced/hpa-orchestrator.yaml
```
