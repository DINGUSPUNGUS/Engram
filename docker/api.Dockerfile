# engram API image. Optional — the blessed local path is `pnpm dev` (see README).
# Build from the repo root:  docker build -f docker/api.Dockerfile -t engram-api .
#
# Run (loopback-only, matching the documented default — security.md):
#   docker run -p 127.0.0.1:8000:8000 -v engram-data:/data engram-api
# Or just:  docker compose up  (see docker-compose.yml at the repo root)
#
# Wider exposure is an explicit, deliberate opt-in (security.md: "Changing the
# bind host is an explicit, documented opt-in") — e.g. `-p 8000:8000` publishes
# to every interface on the host. The container's *internal* bind stays
# 0.0.0.0 regardless: that's a Docker networking requirement (a process bound
# to 127.0.0.1 inside a container's own network namespace is unreachable via
# `-p` from anywhere, including the host) — the host-side `-p` mapping above is
# the actual loopback-only control point.
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
    ENGRAM_API_HOST=0.0.0.0 \
    ENGRAM_API_PORT=8000
VOLUME /data
EXPOSE 8000
# Shell form so ENGRAM_API_HOST/ENGRAM_API_PORT (operations.md) are the actual,
# single source of truth for the bind, not just documentation — an operator
# overriding them (`docker run -e ENGRAM_API_HOST=...`) changes what uvicorn
# does, same as every other engram entrypoint.
CMD uvicorn engram_api.main:app --host "$ENGRAM_API_HOST" --port "$ENGRAM_API_PORT"
