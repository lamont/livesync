# syntax=docker/dockerfile:1
#
# Patched copy of vendor/obsidian-livesync/src/apps/cli/Dockerfile.
#
# Upstream's builder stage copies only package.json (no lockfile), so every
# build re-resolves dependencies from the registry. The CLI source imports
# @smithy/util-retry directly but only receives it as a transitive (phantom)
# dependency — a registry-side bump made fresh resolutions stop hoisting it,
# breaking the vite build. This copy ships package-lock.json so npm installs
# the locked tree. (Strict `npm ci` is impossible: upstream's lockfile is
# already out of sync with its package.json — missing picomatch@4.0.5.)
#
# Build context is still the submodule root:
#   docker build -f livesync-cli.Dockerfile -t livesync-cli:local vendor/obsidian-livesync

# ─────────────────────────────────────────────────────────────────────────────
#  Stage 1 — builder
# ─────────────────────────────────────────────────────────────────────────────
FROM node:22-slim AS builder

# Build tools required by native Node.js addons (mainly leveldown)
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install workspace dependencies first (layer-cache friendly)
COPY package.json package-lock.json ./
RUN npm install

# Copy the full source tree and build the CLI bundle
COPY . .
RUN cd src/apps/cli && npm run build

# ─────────────────────────────────────────────────────────────────────────────
#  Stage 2 — runtime-deps
# ─────────────────────────────────────────────────────────────────────────────
FROM node:22-slim AS runtime-deps

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /deps

# runtime-package.json lists only the packages that Vite leaves external
# (no lockfile exists for it upstream, so this stays npm install)
COPY src/apps/cli/runtime-package.json ./package.json
RUN npm install --omit=dev

# ─────────────────────────────────────────────────────────────────────────────
#  Stage 3 — runtime
# ─────────────────────────────────────────────────────────────────────────────
FROM node:22-slim

WORKDIR /app

COPY --from=runtime-deps /deps/node_modules ./node_modules
COPY --from=builder /build/src/apps/cli/dist ./dist

COPY src/apps/cli/docker-entrypoint.sh /usr/local/bin/livesync-cli
RUN chmod +x /usr/local/bin/livesync-cli

VOLUME ["/data"]

ENTRYPOINT ["livesync-cli"]
