"""Tests for portal routes."""

OIDC_HEADER = "x-amzn-oidc-data"


def test_healthz_no_auth_required(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_home_returns_user_info(client, admin_token):
    r = client.get("/", headers={OIDC_HEADER: admin_token})
    assert r.status_code == 200
    body = r.json()
    assert "user" in body
    assert "groups" in body
    assert "is_admin" in body


def test_home_reflects_correct_identity(client, user_token):
    r = client.get("/", headers={OIDC_HEADER: user_token})
    body = r.json()
    assert body["user"] == "user@example.com"
    assert body["is_admin"] is False
