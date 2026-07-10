# Convenience aliases. Everything delegates to pnpm/turbo/uv, which are the
# actual entry points — use those directly if you don't have `make` (Windows).

.PHONY: setup dev build lint typecheck test format clean

setup:
	pnpm install
	uv sync

dev:
	pnpm turbo run dev

build:
	pnpm turbo run build

lint:
	pnpm turbo run lint
	pnpm run lint:architecture

typecheck:
	pnpm turbo run typecheck

test:
	pnpm turbo run test

format:
	pnpm biome format --write .
	uv run ruff format .

clean:
	pnpm -r exec rm -rf dist .next .turbo || true
