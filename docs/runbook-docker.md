# Docker End-to-End Runbook

## Prerequisites

- Docker Desktop or Docker Engine
- At least 16 GB RAM recommended for local model serving
- Corporate-approved base images mirrored internally if required

## Step 1: Configure environment

```powershell
copy .env.example .env
```

Update values in `.env` as needed, especially `LLM_MODEL` and limits.

## Step 2: Build and start services

```powershell
docker compose -f deploy/docker-compose.yml up --build
```

Services started:
- orchestrator API on 8080
- qdrant on 6333
- ollama-compatible LLM endpoint on 11434

## Step 3: Pull local model in LLM service

```powershell
docker exec -it deploy-llm-1 ollama pull llama3.1:8b-instruct
```

If container name differs, run `docker ps` and update command.

## Step 4: Health check

```powershell
curl http://localhost:8080/health
```

Expected response contains `status: ok`.

## Step 5: Test optimization API

```powershell
curl -X POST http://localhost:8080/optimize \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"doc-1\",\"text\":\"This is a long and unclear paragraph...\",\"objective\":\"Improve clarity\"}"
```

## Step 6: Test compose API for PDF and DOCX generation

```powershell
curl -X POST http://localhost:8080/compose \
  -H "X-User-Id: user-001" \
  -H "X-User-Role: author" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"doc-2\",\"user_prompt\":\"Create executive summary from project notes\",\"source_text\":\"\",\"instructions\":[\"Use headings\",\"Include risks\"],\"output_formats\":[\"pdf\",\"docx\"]}"
```

Expected result contains `optimized_text` and `artifacts` metadata including `artifact_id` and `download_path`.

Use returned `artifact_id` and `download_path` to fetch generated files with the same identity headers.

## Step 7: Stop stack

```powershell
docker compose -f deploy/docker-compose.yml down
```

## Optional advanced stack

Use advanced compose for caching and telemetry:

```powershell
docker compose -f deploy/docker-compose.advanced.yml up --build
```
