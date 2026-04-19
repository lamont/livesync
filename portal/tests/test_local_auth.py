"""Tests for local (HTTP Basic Auth) authentication mode."""

import base64
import os
import tempfile

import pytest
import yaml
from fastapi.testclient import TestClient

OIDC_HEADER = "x-amzn-oidc-data"


def _basic_header(email: str, password: str) -> dict:
    creds = base64.b64encode(f"{email}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def local_app(tmp_path):
    """Create a FastAPI app in local auth mode with a temp users file."""
    users = [
        {"email": "alice@local.dev", "password": "secret", "groups": ["livesync-admin"]},
        {"email": "bob@local.dev", "password": "bob123", "groups": ["eng"]},
    ]
    users_file = tmp_path / "users.yaml"
    users_file.write_text(yaml.dump(users))

    # Set env before importing the module
    os.environ["AUTH_MODE"] = "local"
    os.environ["USERS_FILE"] = str(users_file)

    # Force reimport to pick up new env
    import importlib
    import app.auth
    importlib.reload(app.auth)
    import app.main
    importlib.reload(app.main)

    client = TestClient(app.main.app)
    yield client, users_file

    # Restore defaults
    os.environ["AUTH_MODE"] = "local"
    os.environ.pop("USERS_FILE", None)
    importlib.reload(app.auth)
    importlib.reload(app.main)


def test_local_no_auth_returns_401_with_www_authenticate(local_app):
    client, _ = local_app
    r = client.get("/")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert "Basic" in r.headers["WWW-Authenticate"]


def test_local_valid_admin(local_app):
    client, _ = local_app
    r = client.get("/", headers=_basic_header("alice@local.dev", "secret"))
    assert r.status_code == 200
    assert "alice@local.dev" in r.text


def test_local_valid_regular_user(local_app):
    client, _ = local_app
    r = client.get("/", headers=_basic_header("bob@local.dev", "bob123"))
    assert r.status_code == 200
    assert "bob@local.dev" in r.text


def test_local_wrong_password(local_app):
    client, _ = local_app
    r = client.get("/", headers=_basic_header("alice@local.dev", "wrong"))
    assert r.status_code == 401


def test_local_unknown_user(local_app):
    client, _ = local_app
    r = client.get("/", headers=_basic_header("nobody@local.dev", "x"))
    assert r.status_code == 401


def test_local_jwt_still_works(local_app):
    """In local mode, x-amzn-oidc-data header is still accepted for testing."""
    from tests.conftest import make_token

    client, _ = local_app
    token = make_token("jwt-user@test.com", ["livesync-admin"])
    r = client.get("/", headers={OIDC_HEADER: token})
    assert r.status_code == 200
    assert "jwt-user@test.com" in r.text


def test_local_users_file_hot_reload(local_app):
    """Edits to users.yaml take effect without restart."""
    client, users_file = local_app

    # Initially carol doesn't exist
    r = client.get("/", headers=_basic_header("carol@local.dev", "new"))
    assert r.status_code == 401

    # Add carol to the file
    users = yaml.safe_load(users_file.read_text())
    users.append({"email": "carol@local.dev", "password": "new", "groups": []})
    users_file.write_text(yaml.dump(users))

    # Now carol can log in
    r = client.get("/", headers=_basic_header("carol@local.dev", "new"))
    assert r.status_code == 200
    assert "carol@local.dev" in r.text


def test_healthz_still_public_in_local_mode(local_app):
    client, _ = local_app
    r = client.get("/healthz")
    assert r.status_code == 200
