FROM python:3.12-slim

WORKDIR /app

# Install the package
COPY . .
RUN pip install --no-cache-dir .

# Create data directory
RUN mkdir -p /data

# Default port
EXPOSE 8421

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8421/health')" || exit 1

ENTRYPOINT ["cortex", "serve"]
CMD ["--storage", "sqlite", "--db-path", "/data/cortex.db", "--store-dir", "/data/.cortex", "/data/context.json"]
