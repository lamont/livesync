"""Tests for PUT /api/vaults/{name}/members endpoint."""

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
    set_vault_service(mock_vault_service)
    client = TestClient(app)
    yield client, mock_vault_service
    set_vault_service(None)


@pytest.fixture
def owner_headers():
    return {OIDC_HEADER: make_token("owner@co.com", ["eng"])}


@pytest.fixture
def other_headers():
    return {OIDC_HEADER: make_token("other@co.com", ["eng"])}


@pytest.fixture
def admin_headers():
    return {OIDC_HEADER: make_token("admin@co.com", ["livesync-admin"])}


def _vault(**kwargs):
    defaults = dict(name="team-wiki", owner="owner@co.com", members=["owner@co.com"])
    defaults.update(kwargs)
    return VaultInfo(**defaults)


# ── Add member ───────────────────────────────────────────────────────────────

def test_add_member_as_owner(api_client, owner_headers):
    client, svc = api_client
    svc.get_vault.return_value = _vault()
    svc.share_vault.return_value = _vault(members=["owner@co.com", "bob@co.com"])

    r = client.put(
        "/api/vaults/team-wiki/members",
        json={"add": ["bob@co.com"]},
        headers=owner_headers,
    )

    assert r.status_code == 200
    assert "bob@co.com" in r.json()["members"]
    svc.share_vault.assert_called_once_with("team-wiki", "bob@co.com")


def test_add_member_as_non_owner(api_client, other_headers):
    client, svc = api_client
    svc.get_vault.return_value = _vault()

    r = client.put(
        "/api/vaults/team-wiki/members",
        json={"add": ["bob@co.com"]},
        headers=other_headers,
    )

    assert r.status_code == 403


def test_add_member_as_admin(api_client, admin_headers):
    client, svc = api_client
    svc.get_vault.return_value = _vault()
    svc.share_vault.return_value = _vault(members=["owner@co.com", "bob@co.com"])

    r = client.put(
        "/api/vaults/team-wiki/members",
        json={"add": ["bob@co.com"]},
        headers=admin_headers,
    )

    assert r.status_code == 200
    svc.share_vault.assert_called_once()


# ── Remove member ────────────────────────────────────────────────────────────

def test_remove_member_as_owner(api_client, owner_headers):
    client, svc = api_client
    svc.get_vault.return_value = _vault(members=["owner@co.com", "bob@co.com"])
    svc.unshare_vault.return_value = _vault()

    r = client.put(
        "/api/vaults/team-wiki/members",
        json={"remove": ["bob@co.com"]},
        headers=owner_headers,
    )

    assert r.status_code == 200
    svc.unshare_vault.assert_called_once_with("team-wiki", "bob@co.com")


def test_remove_owner_returns_400(api_client, owner_headers):
    client, svc = api_client
    svc.get_vault.return_value = _vault()
    svc.unshare_vault.side_effect = ValueError("Cannot remove the vault owner")

    r = client.put(
        "/api/vaults/team-wiki/members",
        json={"remove": ["owner@co.com"]},
        headers=owner_headers,
    )

    assert r.status_code == 400
    assert "owner" in r.json()["detail"].lower()


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_update_members_vault_not_found(api_client, owner_headers):
    client, svc = api_client
    svc.get_vault.return_value = None

    r = client.put(
        "/api/vaults/nonexistent/members",
        json={"add": ["bob@co.com"]},
        headers=owner_headers,
    )

    assert r.status_code == 404


def test_update_members_no_auth(api_client):
    client, _ = api_client
    r = client.put("/api/vaults/team-wiki/members", json={"add": ["x@co.com"]})
    assert r.status_code == 401
