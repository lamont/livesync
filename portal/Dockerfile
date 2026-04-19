FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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

ENV SETUP_URI_SCRIPT=/scripts/generate_setupuri.ts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
