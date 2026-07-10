# engram API image. Optional — the blessed local path is `pnpm dev` (see README).
# Build from the repo root:  docker build -f docker/api.Dockerfile -t engram-api .
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Layer-cache dependencies before copying source.
COPY pyproject.toml uv.lock .python-version ./
COPY libs/engram-events/pyproject.toml libs/engram-events/pyproject.toml
COPY libs/engram-core/pyproject.toml libs/engram-core/pyproject.toml
COPY libs/engram-storage-sqlite/pyproject.toml libs/engram-storage-sqlite/pyproject.toml
COPY libs/engram-export-git/pyproject.toml libs/engram-export-git/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/cli/pyproject.toml apps/cli/pyproject.toml
COPY apps/mcp/pyproject.toml apps/mcp/pyproject.toml
RUN uv sync --all-packages --no-dev --no-install-workspace --frozen

COPY libs libs
COPY apps/api apps/api
COPY apps/cli apps/cli
COPY apps/mcp apps/mcp
RUN uv sync --all-packages --no-dev --frozen

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home engram
USER engram
WORKDIR /app
COPY --from=builder --chown=engram:engram /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    ENGRAM_DATA_DIR=/data \
    ENGRAM_API_HOST=0.0.0.0
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "engram_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
