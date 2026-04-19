"""Tests for portal routes."""

from unittest.mock import AsyncMock

from app.models import VaultInfo
from app.routes.api import set_vault_service
from tests.conftest import make_token

OIDC_HEADER = "x-amzn-oidc-data"


def test_healthz_no_auth_required(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_home_redirects_to_welcome_for_new_user(client, user_token):
    """User with no vaults gets redirected to /welcome."""
    r = client.get("/", headers={OIDC_HEADER: user_token}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/welcome"


def test_home_returns_vault_list_page(client, admin_token):
    svc = AsyncMock()
    svc.list_vaults_for_user.return_value = [
        VaultInfo(name="wiki", owner="admin@example.com", members=["admin@example.com"]),
    ]
    set_vault_service(svc)

    r = client.get("/", headers={OIDC_HEADER: admin_token})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "LiveSync Portal" in r.text
    assert "admin@example.com" in r.text
    assert "wiki" in r.text


def test_home_reflects_correct_identity(client, user_token):
    svc = AsyncMock()
    svc.list_vaults_for_user.return_value = [
        VaultInfo(name="v1", owner="user@example.com", members=["user@example.com"]),
    ]
    set_vault_service(svc)

    r = client.get("/", headers={OIDC_HEADER: user_token})
    assert r.status_code == 200
    assert "user@example.com" in r.text


# ── Welcome route ────────────────────────────────────────────────────────────

def test_welcome_page_renders(client, user_token):
    r = client.get("/welcome", headers={OIDC_HEADER: user_token})
    assert r.status_code == 200
    assert "Welcome to LiveSync" in r.text


def test_welcome_requires_auth(client):
    r = client.get("/welcome")
    assert r.status_code == 401


def test_welcome_post_creates_vault(client, user_token):
    svc = AsyncMock()
    svc.create_vault.return_value = VaultInfo(
        name="new-vault", owner="user@example.com", members=["user@example.com"],
    )
    svc.list_vaults_for_user.return_value = [svc.create_vault.return_value]
    set_vault_service(svc)

    r = client.post(
        "/welcome",
        data={"name": "new-vault"},
        headers={OIDC_HEADER: user_token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    svc.create_vault.assert_called_once()


def test_welcome_post_duplicate_shows_error(client, user_token):
    svc = AsyncMock()
    svc.create_vault.side_effect = ValueError("Vault 'taken' already exists")
    set_vault_service(svc)

    r = client.post(
        "/welcome",
        data={"name": "taken"},
        headers={OIDC_HEADER: user_token},
    )
    assert r.status_code == 200
    assert "already exists" in r.text


# ── Admin route ──────────────────────────────────────────────────────────────

def test_admin_page_as_admin(client, admin_token):
    r = client.get("/admin/", headers={OIDC_HEADER: admin_token})
    assert r.status_code == 200
    assert "Admin Dashboard" in r.text


def test_admin_page_as_non_admin(client, user_token):
    r = client.get("/admin/", headers={OIDC_HEADER: user_token})
    assert r.status_code == 403


# ── Vault detail route ───────────────────────────────────────────────────────

def test_vault_detail_as_owner(client, user_token):
    svc = AsyncMock()
    svc.get_vault.return_value = VaultInfo(
        name="my-wiki", owner="user@example.com",
        members=["user@example.com"],
    )
    set_vault_service(svc)

    r = client.get("/vaults/my-wiki/detail", headers={OIDC_HEADER: user_token})
    assert r.status_code == 200
    assert "my-wiki" in r.text
    assert "user@example.com" in r.text


def test_vault_detail_as_non_member(client, user_token):
    svc = AsyncMock()
    svc.get_vault.return_value = VaultInfo(
        name="private", owner="other@example.com",
        members=["other@example.com"],
    )
    set_vault_service(svc)

    r = client.get("/vaults/private/detail", headers={OIDC_HEADER: user_token})
    assert r.status_code == 403


def test_vault_detail_not_found(client, user_token):
    svc = AsyncMock()
    svc.get_vault.return_value = None
    set_vault_service(svc)

    r = client.get("/vaults/nonexistent/detail", headers={OIDC_HEADER: user_token})
    assert r.status_code == 404
