FROM ghcr.io/astral-sh/uv:python3.12-alpine

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY publish.py ./

CMD ["uv", "run", "--no-sync", "python", "publish.py"]
