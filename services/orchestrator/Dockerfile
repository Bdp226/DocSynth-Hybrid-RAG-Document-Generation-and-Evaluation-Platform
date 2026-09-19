# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1 - builder
# Dependencies are compiled into an isolated virtualenv so the runtime image
# ships no build toolchain, no pip cache, and no compiler headers.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 - runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG SERVICE_VERSION=1.0.0

LABEL org.opencontainers.image.title="DocSynth Orchestrator" \
      org.opencontainers.image.description="Enterprise multi-modal document synthesis engine" \
      org.opencontainers.image.version="${SERVICE_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/your-org/docsynth"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    GIT_COMMIT=${GIT_COMMIT} \
    BUILD_TIME=${BUILD_TIME} \
    ARTIFACT_STORAGE_DIR=/var/lib/docsynth/artifacts

# curl is required by HEALTHCHECK; nothing else is installed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 docsynth \
    && useradd --system --uid 10001 --gid docsynth --create-home --home-dir /home/docsynth docsynth

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=docsynth:docsynth app /app/app

# Writable state lives outside the read-only application tree so the container
# can run with a read-only root filesystem.
RUN mkdir -p /var/lib/docsynth/artifacts /app/build \
    && chown -R docsynth:docsynth /var/lib/docsynth /app/build

USER docsynth

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8080/healthz || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers ${UVICORN_WORKERS:-2}"]
