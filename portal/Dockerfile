FROM node:22-alpine AS quartz

RUN apk add --no-cache git
WORKDIR /quartz
RUN git clone --depth 1 https://github.com/jackyzha0/quartz.git . \
    && npm ci

# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Node.js 22 — needed for Quartz builds
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Quartz v4 static site generator
COPY --from=quartz /quartz /quartz

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
