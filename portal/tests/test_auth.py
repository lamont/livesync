"""Tests for JWT (OIDC) authentication.

These tests use the x-amzn-oidc-data header path.  The ``client`` fixture
runs the app with whatever AUTH_MODE is set (default: local), but the OIDC
header takes priority in any mode.
"""

import os

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_token

OIDC_HEADER = "x-amzn-oidc-data"


@pytest.fixture
def oidc_client():
    """Client with AUTH_MODE=oidc so unauthenticated requests get JSON 401."""
    os.environ["AUTH_MODE"] = "oidc"
    import importlib, app.auth, app.main
    importlib.reload(app.auth)
    importlib.reload(app.main)
    client = TestClient(app.main.app)
    yield client
    os.environ["AUTH_MODE"] = "local"
    importlib.reload(app.auth)
    importlib.reload(app.main)


def test_oidc_no_auth_header_returns_401(oidc_client):
    r = oidc_client.get("/")
    assert r.status_code == 401
    assert "Missing" in r.json()["detail"]


def test_invalid_token_returns_401(client):
    r = client.get("/", headers={OIDC_HEADER: "not-a-jwt"})
    assert r.status_code == 401
    assert "Invalid token" in r.json()["detail"]


def test_expired_token_returns_401(client, expired_token):
    r = client.get("/", headers={OIDC_HEADER: expired_token})
    assert r.status_code == 401


def test_wrong_signing_key_returns_401(client):
    from jose import jwt

    token = jwt.encode(
        {"email": "bad@example.com", "sub": "bad", "iss": "test", "iat": 0, "exp": 99999999999},
        "wrong-key",
        algorithm="HS256",
    )
    r = client.get("/", headers={OIDC_HEADER: token})
    assert r.status_code == 401


def test_valid_admin_token(client, admin_token):
    r = client.get("/", headers={OIDC_HEADER: admin_token})
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == "admin@example.com"
    assert body["is_admin"] is True
    assert "livesync-admin" in body["groups"]


def test_valid_regular_user_token(client, user_token):
    r = client.get("/", headers={OIDC_HEADER: user_token})
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == "user@example.com"
    assert body["is_admin"] is False


def test_groups_as_comma_string():
    """Okta sometimes sends groups as a comma-separated string."""
    from app.auth import _user_from_claims

    user = _user_from_claims({"email": "x@co.com", "groups": "eng,livesync-admin,ops"})
    assert user.groups == ["eng", "livesync-admin", "ops"]
    assert user.is_admin is True


def test_groups_from_custom_claim():
    """ALB may pass groups under custom:groups."""
    from app.auth import _user_from_claims

    user = _user_from_claims({"email": "x@co.com", "custom:groups": ["livesync-admin"]})
    assert user.is_admin is True


def test_missing_groups_defaults_empty():
    from app.auth import _user_from_claims

    user = _user_from_claims({"email": "x@co.com"})
    assert user.groups == []
    assert user.is_admin is False
