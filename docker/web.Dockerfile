# engram web dashboard image. Optional — local dev uses `pnpm dev`.
# Build from the repo root:  docker build -f docker/web.Dockerfile -t engram-web .
FROM node:22-slim AS builder
WORKDIR /repo
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages packages
RUN pnpm install --frozen-lockfile --filter @engram/web...
COPY apps/web apps/web
ENV NEXT_OUTPUT=standalone
RUN pnpm --filter @engram/web build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
RUN useradd --create-home engram
USER engram
COPY --from=builder --chown=engram:engram /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=engram:engram /repo/apps/web/.next/static ./apps/web/.next/static
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
