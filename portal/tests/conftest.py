import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app
from app.routes.api import set_vault_service

SIGNING_KEY = "dev-secret-key"


class _FakeVaultService:
    """Minimal vault service stub that returns empty results."""
    async def list_vaults_for_user(self, email, groups):
        return []

    async def get_vault(self, name):
        return None

    async def get_setup_uri(self, vault_name, email):
        return {"setup_uri": "obsidian://test", "uri_passphrase": "test"}

    async def list_all_vaults(self):
        return []

    async def share_vault(self, vault_name, email):
        return None

    async def unshare_vault(self, vault_name, email):
        return None


@pytest.fixture(autouse=True)
def _mock_vault_service():
    """Inject a fake vault service so tests don't need CouchDB."""
    svc = _FakeVaultService()
    set_vault_service(svc)
    yield
    set_vault_service(None)


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
