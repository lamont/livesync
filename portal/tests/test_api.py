"""Tests for vault API routes (portal/app/routes/api.py).

Uses FastAPI TestClient with the vault service mocked via set_vault_service.
Auth is handled by passing a valid JWT via x-amzn-oidc-data header.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import VaultInfo
from app.routes.api import set_vault_service
from tests.conftest import make_token

OIDC_HEADER = "x-amzn-oidc-data"


@pytest.fixture
def mock_vault_service():
    return AsyncMock()


@pytest.fixture
def api_client(mock_vault_service):
    """TestClient with a mock vault service injected."""
    set_vault_service(mock_vault_service)
    client = TestClient(app)
    yield client, mock_vault_service
    set_vault_service(None)


@pytest.fixture
def admin_headers():
    return {OIDC_HEADER: make_token("admin@co.com", ["livesync-admin"])}


@pytest.fixture
def user_headers():
    return {OIDC_HEADER: make_token("user@co.com", ["eng"])}


# ── POST /api/vaults ────────────────────────────────────────────────────────

def test_create_vault(api_client, admin_headers):
    client, svc = api_client
    svc.create_vault.return_value = VaultInfo(
        name="new-vault", owner="admin@co.com", members=["admin@co.com"]
    )

    r = client.post(
        "/api/vaults",
        json={"name": "new-vault"},
        headers=admin_headers,
    )

    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "new-vault"
    assert body["owner"] == "admin@co.com"
    svc.create_vault.assert_called_once()


def test_create_vault_encrypted_only(api_client, admin_headers):
    client, svc = api_client
    svc.create_vault.return_value = VaultInfo(
        name="secret", owner="admin@co.com", members=["admin@co.com"],
        encrypted_only=True,
    )

    r = client.post(
        "/api/vaults",
        json={"name": "secret", "encrypted_only": True},
        headers=admin_headers,
    )

    assert r.status_code == 201
    assert r.json()["encrypted_only"] is True


def test_create_vault_duplicate_returns_409(api_client, admin_headers):
    client, svc = api_client
    svc.create_vault.side_effect = ValueError("Vault 'taken' already exists")

    r = client.post(
        "/api/vaults",
        json={"name": "taken"},
        headers=admin_headers,
    )

    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_create_vault_no_auth(api_client):
    client, _ = api_client
    r = client.post("/api/vaults", json={"name": "x"})
    assert r.status_code == 401


def test_create_vault_missing_name(api_client, admin_headers):
    client, _ = api_client
    r = client.post("/api/vaults", json={}, headers=admin_headers)
    assert r.status_code == 422  # validation error


# ── GET /api/vaults ──────────────────────────────────────────────────────────

def test_list_vaults(api_client, user_headers):
    client, svc = api_client
    svc.list_vaults_for_user.return_value = [
        VaultInfo(name="v1", owner="user@co.com", members=["user@co.com"]),
        VaultInfo(name="v2", owner="other@co.com", members=["other@co.com", "user@co.com"]),
    ]

    r = client.get("/api/vaults", headers=user_headers)

    assert r.status_code == 200
    vaults = r.json()
    assert len(vaults) == 2
    assert vaults[0]["name"] == "v1"


def test_list_vaults_empty(api_client, user_headers):
    client, svc = api_client
    svc.list_vaults_for_user.return_value = []

    r = client.get("/api/vaults", headers=user_headers)

    assert r.status_code == 200
    assert r.json() == []


# ── GET /api/vaults/{name} ───────────────────────────────────────────────────

def test_get_vault_detail(api_client, user_headers):
    client, svc = api_client
    svc.get_vault.return_value = VaultInfo(
        name="team-wiki", owner="admin@co.com",
        members=["admin@co.com", "user@co.com"],
    )

    r = client.get("/api/vaults/team-wiki", headers=user_headers)

    assert r.status_code == 200
    assert r.json()["name"] == "team-wiki"


def test_get_vault_not_found(api_client, user_headers):
    client, svc = api_client
    svc.get_vault.return_value = None

    r = client.get("/api/vaults/nonexistent", headers=user_headers)

    assert r.status_code == 404


# ── GET /api/vaults/{name}/setup-uri ─────────────────────────────────────────

def test_get_setup_uri(api_client, user_headers):
    client, svc = api_client
    svc.get_setup_uri.return_value = {
        "setup_uri": "obsidian://setuplivesync?settings=encrypted-blob",
        "uri_passphrase": "autumn-river",
    }

    r = client.get("/api/vaults/team-wiki/setup-uri", headers=user_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["setup_uri"].startswith("obsidian://setuplivesync?")
    assert body["uri_passphrase"] == "autumn-river"
    svc.get_setup_uri.assert_called_once_with("team-wiki", "user@co.com")
