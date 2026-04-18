import time

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app

SIGNING_KEY = "dev-secret-key"


@pytest.fixture
def client():
    return TestClient(app)


def make_token(email: str, groups: list[str] | None = None, expired: bool = False) -> str:
    now = int(time.time())
    claims = {
        "email": email,
        "groups": groups or [],
        "sub": email,
        "iss": "https://livesync-test",
        "iat": now,
        "exp": now + (-3600 if expired else 3600),
    }
    return jwt.encode(claims, SIGNING_KEY, algorithm="HS256")


@pytest.fixture
def admin_token():
    return make_token("admin@example.com", ["eng", "livesync-admin"])


@pytest.fixture
def user_token():
    return make_token("user@example.com", ["eng"])


@pytest.fixture
def expired_token():
    return make_token("expired@example.com", expired=True)
