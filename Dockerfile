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

# Create writable data directory for identities, outputs, and mounted files.
RUN mkdir -p /data/.cortex && chown -R cortex:cortex /data

USER cortex

ENTRYPOINT ["cortex"]
CMD ["--help"]
