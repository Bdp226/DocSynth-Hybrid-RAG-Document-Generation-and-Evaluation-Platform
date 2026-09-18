# Kubernetes End-to-End Runbook

## Prerequisites

- Kubernetes cluster (on-prem or private cloud)
- Internal container registry
- kubectl access with namespace create privileges
- GPU node pool for LLM workloads (recommended)

## Step 1: Build and push orchestrator image

```powershell
cd services/orchestrator
docker build -t <registry>/doc-optimizer-orchestrator:0.1.0 .
docker push <registry>/doc-optimizer-orchestrator:0.1.0
```

## Step 2: Update deployment image

Edit image field in `deploy/k8s/orchestrator-deployment.yaml` to your internal registry.

## Step 3: Deploy baseline services

```powershell
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/vector-db-deployment.yaml
kubectl apply -f deploy/k8s/orchestrator-deployment.yaml
```

## Step 4: Deploy advanced production controls

```powershell
kubectl apply -f deploy/k8s/advanced/configmap.yaml
kubectl apply -f deploy/k8s/advanced/llm-deployment.yaml
kubectl apply -f deploy/k8s/advanced/networkpolicy.yaml
kubectl apply -f deploy/k8s/advanced/hpa-orchestrator.yaml
```

## Step 5: Validate rollout

```powershell
kubectl -n doc-optimizer get pods
kubectl -n doc-optimizer get svc
kubectl -n doc-optimizer logs deploy/orchestrator --tail=100
```

## Step 6: Smoke test in-cluster

```powershell
kubectl -n doc-optimizer port-forward svc/orchestrator 8080:8080
curl http://localhost:8080/health
```

Then call `POST /compose` to validate optimized text and artifact generation in-cluster.
Include `X-User-Id` and `X-User-Role` headers in all requests.

## Step 7: Rollback procedure

```powershell
kubectl -n doc-optimizer rollout history deploy/orchestrator
kubectl -n doc-optimizer rollout undo deploy/orchestrator --to-revision=1
```

## Step 8: Day-2 operations

- Monitor latency/error dashboards
- Review policy-flagged requests daily
- Run weekly relevance and regression evaluations
