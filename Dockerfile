# ---------- builder stage ----------
FROM python:3.12-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir --prefix=/install ".[full]"

# ---------- runtime stage ----------
FROM python:3.12-slim

# Non-root user
RUN groupadd -r cortex && useradd -r -g cortex -u 1000 cortex

# Copy installed packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /build /app

WORKDIR /app

# Create data and config directories
RUN mkdir -p /data/.cortex /etc/cortex && \
    chown -R cortex:cortex /data

# Copy default config
COPY deploy/cortex.ini /etc/cortex/cortex.ini

EXPOSE 8421

# Health check using stdlib (no curl needed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8421/health')" || exit 1

USER cortex

ENTRYPOINT ["cortex", "serve"]
CMD ["--config", "/etc/cortex/cortex.ini", "--storage", "sqlite", "--db-path", "/data/cortex.db", "--store-dir", "/data/.cortex", "/data/context.json"]
