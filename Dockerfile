# -----------------------------------------------------------------------------
# KestrelCOP Tactical Edge Node Dockerfile
# Multi-stage, security-hardened, uv-optimized Python 3.12 image
# -----------------------------------------------------------------------------

FROM python:3.12-slim AS builder

# Install build dependencies for C-extensions and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Astral uv
COPY --from=ghcr.io/astral-sh/uv:0.5.26 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first for maximum layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source code
COPY edge_node ./edge_node
COPY README.md LICENSE ./

# Sync project installation
RUN uv sync --frozen --no-dev

# -----------------------------------------------------------------------------
# Final Production Runtime Stage
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Install minimal runtime shared libraries for OpenCV & video decode
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Security: Create non-root tactical operator user
RUN groupadd -g 10001 kestrel && \
    useradd -u 10001 -g kestrel -s /bin/bash -m kestrel

WORKDIR /app

# Copy virtual environment and application from builder stage
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/edge_node /app/edge_node
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KESTREL_MOCK_MODE=true \
    KESTREL_BROKER_HOST=mosquitto \
    KESTREL_BROKER_PORT=1883

# Switch to unprivileged user
USER kestrel

EXPOSE 8080

ENTRYPOINT ["python", "-m", "edge_node.main"]
