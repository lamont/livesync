from fastapi import FastAPI

from .auth import AuthMiddleware
from .routes import api, health, home

app = FastAPI(title="LiveSync Portal", version="0.1.0")

app.add_middleware(AuthMiddleware)

app.include_router(health.router)
app.include_router(home.router)
app.include_router(api.router)
