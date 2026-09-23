# syntax=docker/dockerfile:1

# Build stage - install dependencies using uv
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# Install git (needed for git dependencies in pyproject.toml)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies into the virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy the application code
COPY . .

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Runtime stage - minimal image
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home appuser

# Install runtime dependencies (for psycopg binary)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder. `--chown` here (not a later
# `RUN chown -R`) matters for image size: a chown after the fact touches every
# file's metadata, and on the overlay filesystem that forces a full copy-up of
# the venv into a brand-new layer -- silently doubling the image.
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv

# Copy application code. `pyproject.toml` declares no build-system, so uv
# never installs this project into the venv — `app` and `skillkit` are both
# imported from the working directory, and each one has to be copied here by
# name. Missing `skillkit` is not a lint or test failure: it only surfaces as
# `ModuleNotFoundError` when the container starts.
COPY --from=builder --chown=appuser:appgroup /app/app /app/app
COPY --from=builder --chown=appuser:appgroup /app/skillkit /app/skillkit
COPY --from=builder --chown=appuser:appgroup /app/alembic /app/alembic
COPY --from=builder --chown=appuser:appgroup /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=appuser:appgroup /app/entrypoint.sh /app/entrypoint.sh

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN chmod +x /app/entrypoint.sh

USER appuser

# Expose the application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')" || exit 1

# Use entrypoint to run migrations before starting the app
ENTRYPOINT ["/app/entrypoint.sh"]
# --timeout-graceful-shutdown: protocol SSE sessions live as long as a chat tab
# is open, so a SIGTERM would otherwise wait on them past the platform's kill
# deadline and the lifespan shutdown (Langfuse flush, pool close) never runs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "8"]
