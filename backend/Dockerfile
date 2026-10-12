# =============================================================================
# Backend Dockerfile — Multi-stage build with uv
# =============================================================================
# Produces a slim production image with only runtime dependencies.
# Build:  docker build -t local-ai-backend .
# Run:    docker run --env-file .env -p 8000:8000 local-ai-backend
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build — install dependencies with uv
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# System deps needed for building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.lock ./

# Install only production dependencies (no dev extras)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./

# Test image target keeps pytest and test sources out of the production image.
FROM builder AS test
RUN uv sync --frozen --extra dev --no-install-project
COPY tests/ tests/
CMD ["pytest", "-q"]

# ---------------------------------------------------------------------------
# Stage 2: Runtime — slim image with only what's needed
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Runtime system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the venv and app from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app app/
COPY --from=builder /app/alembic alembic/
COPY --from=builder /app/alembic.ini ./
COPY --from=builder /app/pyproject.toml ./

# Create data directories
RUN mkdir -p data/uploads data/chroma

# Ensure the venv python is used
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# Run migrations then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
