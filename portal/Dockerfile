FROM node:22-alpine AS quartz

# coreutils: quartz's CLI shebang uses `env -S`, which busybox env lacks
RUN apk add --no-cache git coreutils
WORKDIR /quartz
# Pinned Quartz v5 release; bump the tag (and refresh quartz-template/) to upgrade.
RUN git clone --depth 1 --branch v5.0.0 https://github.com/jackyzha0/quartz.git . \
    && npm ci

# Vendored config + plugin lockfile (trimmed to the plugins the config uses).
# The builder rewrites quartz.config.yaml from the template (pageTitle
# sentinel) before each vault build.
COPY quartz-template/quartz.lock.json ./quartz.lock.json
COPY quartz-template/quartz.config.yaml ./quartz.config.template.yaml
# Plugins declare their build toolchain as regular deps, so npm prune inside
# each plugin dir is what actually keeps the image size sane. Do NOT run
# `npx quartz plugin prune` here — it deletes dirs the generated plugin
# loader still imports, breaking every subsequent build.
# Keep .quartz/plugins/*/.git: the loader verifies each plugin's pinned
# commit against the lockfile via git and re-fetches anything unverifiable.
RUN cp quartz.config.template.yaml quartz.config.yaml \
    && npx quartz plugin install \
    && for d in .quartz/plugins/*/; do (cd "$d" && npm prune --omit=dev); done \
    && rm -rf /root/.npm

# Every plugin vendors its own node_modules (~30 copies of the same
# toolchain); hardlinking identical files reclaims ~1.7GB in the final image.
COPY scripts/dedupe_hardlink.py /tmp/dedupe_hardlink.py
RUN apk add --no-cache python3 \
    && python3 /tmp/dedupe_hardlink.py /quartz

# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Node.js 22 — needed for Quartz builds
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Quartz v5 static site generator (with pre-installed community plugins).
# cp -a instead of COPY: COPY expands the hardlinks created by the dedupe
# step back into ~30 duplicate toolchain copies (+1.7GB).
RUN --mount=type=bind,from=quartz,source=/quartz,target=/mnt/quartz \
    cp -a /mnt/quartz /quartz

# Deno — needed for generate_setupuri.ts (Setup URI generation)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno

WORKDIR /app

# Install Python dependencies first (cache-friendly layer)
COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml

# Setup URI generator (same script used by sync and agent containers)
COPY generate_setupuri.ts /scripts/generate_setupuri.ts

COPY app/ app/
COPY templates/ templates/

# Pre-create static output dir for Quartz builds
RUN mkdir -p /static

ENV SETUP_URI_SCRIPT=/scripts/generate_setupuri.ts
ENV QUARTZ_DIR=/quartz
ENV VAULTS_DIR=/vaults
ENV STATIC_DIR=/static

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
