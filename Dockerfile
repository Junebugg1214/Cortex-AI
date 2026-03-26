# ---------- builder stage ----------
FROM python:3.12-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir --prefix=/install ".[full]"

# ---------- runtime stage ----------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Cortex"
LABEL org.opencontainers.image.description="Self-hosted, user-owned Git for AI Memory runtime."
LABEL org.opencontainers.image.url="https://github.com/Junebugg1214/Cortex-AI"
LABEL org.opencontainers.image.source="https://github.com/Junebugg1214/Cortex-AI"
LABEL org.opencontainers.image.licenses="MIT"

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
