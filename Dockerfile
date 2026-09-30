# -----------------------------------------------------------------------------
# KestrelCOP Tactical Edge Node Dockerfile
# Multi-stage, size-optimized, security-hardened Python 3.12 image
# Aggressively strips compilation tools, headers, and caches for field deployment
# -----------------------------------------------------------------------------

# Stage 1: Build & Dependency Resolution
FROM python:3.12-slim AS builder

# Install temporary build toolchain for compiling binary wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Install Astral uv fast package manager
COPY --from=ghcr.io/astral-sh/uv:0.5.26 /uv /uvx /bin/

WORKDIR /app

# Cache dependencies layer
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY edge_node ./edge_node
COPY README.md LICENSE ./

# Complete project installation
RUN uv sync --frozen --no-dev

# Aggressively strip unused files and shared library symbols to minimize image footprint
RUN find /app/.venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -name "*.pyc" -delete && \
    find /app/.venv -name "*.so*" -exec strip --strip-unneeded {} + 2>/dev/null || true

# -----------------------------------------------------------------------------
# Stage 2: Minimal Tactical Edge Production Runtime
# Stripped of all compilers, build tools, pip, and temporary caches
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Install only essential shared runtime libraries (libglib and libgomp for ONNX/OpenCV headless)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/* /var/tmp/*

# Security: Dedicated unprivileged tactical operator
RUN groupadd -g 10001 kestrel && \
    useradd -u 10001 -g kestrel -s /sbin/nologin -m kestrel

WORKDIR /app

# Copy isolated virtual environment and application code from builder
COPY --from=builder --chown=kestrel:kestrel /app/.venv /app/.venv
COPY --from=builder --chown=kestrel:kestrel /app/edge_node /app/edge_node
COPY --from=builder --chown=kestrel:kestrel /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KESTREL_MOCK_MODE=true \
    KESTREL_BROKER_HOST=mosquitto \
    KESTREL_BROKER_PORT=1883

# Run as non-root
USER kestrel

EXPOSE 8080

ENTRYPOINT ["python", "-m", "edge_node.main"]
