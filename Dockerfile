# syntax=docker/dockerfile:1.7

# ---------- builder stage ----------
FROM python:3.12-slim AS builder

WORKDIR /build

# Keep the default runtime image lean. The embedding extra pulls the PyTorch/CUDA
# stack and can add several minutes to CI builds; opt into it with
# --build-arg CORTEX_EXTRAS=full when local sentence-transformer embeddings are
# required inside the container.
ARG CORTEX_EXTRAS=server,fast,model
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
RUN --mount=type=cache,target=/root/.cache/pip python - <<'PY'
import os
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as handle:
    project = tomllib.load(handle)["project"]

dependencies = list(project.get("dependencies") or [])
optional_dependencies = project.get("optional-dependencies") or {}
for extra in [item.strip() for item in os.environ.get("CORTEX_EXTRAS", "").split(",") if item.strip()]:
    if extra not in optional_dependencies:
        raise SystemExit(f"Unknown CORTEX_EXTRAS value: {extra}")
    dependencies.extend(optional_dependencies[extra])

if dependencies:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--prefix=/install", *dependencies])
PY

COPY . .
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install --no-deps .

# ---------- runtime stage ----------
FROM python:3.12-slim

ARG CORTEX_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="Cortex"
LABEL org.opencontainers.image.description="Self-hosted, user-owned Git for AI Memory runtime."
LABEL org.opencontainers.image.url="https://github.com/Junebugg1214/Cortex-AI"
LABEL org.opencontainers.image.source="https://github.com/Junebugg1214/Cortex-AI"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.version="${CORTEX_VERSION}"
LABEL org.opencontainers.image.revision="${VCS_REF}"

# Non-root user
RUN groupadd -r cortex && useradd -r -g cortex -u 1000 cortex

# Copy installed packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /build /app

WORKDIR /app

# Create writable data directory for identities, outputs, and mounted files.
RUN mkdir -p /data/.cortex && chown -R cortex:cortex /data

ENV CORTEX_STORE_DIR=/data/.cortex
EXPOSE 8766

USER cortex

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD python -c "import json, urllib.request; data=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/v1/health').read().decode('utf-8')); raise SystemExit(0 if data.get('status') == 'ok' else 1)"

ENTRYPOINT ["cortexd"]
CMD ["--config", "/data/.cortex/config.toml"]
