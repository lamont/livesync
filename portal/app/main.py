from fastapi import FastAPI

from .auth import JWTAuthMiddleware
from .routes import health, home

app = FastAPI(title="LiveSync Portal", version="0.1.0")

app.add_middleware(JWTAuthMiddleware)

app.include_router(health.router)
app.include_router(home.router)
