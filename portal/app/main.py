import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import Response

from .auth import AuthMiddleware, logout_response
from .couch import CouchClient
from .metrics import (
    HTTP_DURATION,
    HTTP_REQUESTS,
    _normalize_endpoint,
    gauge_refresh_loop,
    metrics_output,
)
from .quartz_builder import QuartzBuilder
from .routes import admin, api, health, home, vaults, welcome

logging.basicConfig(level=logging.INFO)

_builder_task: asyncio.Task | None = None
_gauge_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _builder_task, _gauge_task
    couch = CouchClient(
        base_url=os.environ.get("COUCHDB_URI", "http://couchdb:5984"),
        admin_user=os.environ.get("COUCHDB_USER", "admin"),
        admin_password=os.environ.get("COUCHDB_PASSWORD", ""),
    )
    builder = QuartzBuilder(couch)
    _builder_task = asyncio.create_task(builder.run_loop())
    _gauge_task = asyncio.create_task(gauge_refresh_loop(couch))
    yield
    for task in (_builder_task, _gauge_task):
        if task:
            task.cancel()


app = FastAPI(title="LiveSync Portal", version="0.3.0", lifespan=lifespan)

app.add_middleware(AuthMiddleware)

app.include_router(health.router)
app.include_router(home.router)
app.include_router(welcome.router)
app.include_router(admin.router)
app.include_router(api.router)
app.include_router(vaults.router)


@app.get("/logout", include_in_schema=False)
async def logout():
    return logout_response()


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return Response(content=metrics_output(), media_type="text/plain; version=0.0.4")


@app.middleware("http")
async def http_metrics_middleware(request: Request, call_next):
    endpoint = _normalize_endpoint(request.url.path)
    method = request.method
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    HTTP_REQUESTS.labels(method=method, endpoint=endpoint, status=response.status_code).inc()
    HTTP_DURATION.labels(method=method, endpoint=endpoint).observe(elapsed)
    return response
