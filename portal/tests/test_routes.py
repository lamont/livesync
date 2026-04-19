"""Tests for portal routes."""

OIDC_HEADER = "x-amzn-oidc-data"


def test_healthz_no_auth_required(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_home_returns_vault_list_page(client, admin_token):
    r = client.get("/", headers={OIDC_HEADER: admin_token})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "LiveSync Portal" in r.text
    assert "admin@example.com" in r.text


def test_home_reflects_correct_identity(client, user_token):
    r = client.get("/", headers={OIDC_HEADER: user_token})
    assert r.status_code == 200
    assert "user@example.com" in r.text
