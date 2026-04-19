"""Tests for CouchDB client (portal/app/couch.py).

These tests mock the HTTP layer with respx so they run without a real CouchDB.
Integration tests against real CouchDB are in scripts/smoke-test.sh.
"""

import pytest
import respx
from httpx import Response

from app.couch import CouchClient

COUCH_URL = "http://couchdb:5984"


@pytest.fixture
def couch():
    return CouchClient(COUCH_URL, "admin", "password")


# ── ensure_user ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_user_creates_new_user(couch):
    """First call for an email creates a CouchDB user doc and stores the password."""
    with respx.mock(base_url=COUCH_URL) as mock:
        # Ensure passwords DB exists
        mock.put("/livesync-passwords").respond(412, json={"error": "file_exists"})
        # No stored password yet
        mock.get("/livesync-passwords/pwd:alice@co.com").respond(404)
        # Check if user exists → 404 (not found)
        mock.get("/_users/org.couchdb.user:alice@co.com").respond(404)
        # Create user → 201
        mock.put("/_users/org.couchdb.user:alice@co.com").respond(201, json={"ok": True})
        # Store password
        mock.put("/livesync-passwords/pwd:alice@co.com").respond(201, json={"ok": True})

        password = await couch.ensure_user("alice@co.com")

        assert isinstance(password, str)
        assert len(password) >= 16


@pytest.mark.asyncio
async def test_ensure_user_returns_existing_password(couch):
    """If user already exists, return the stored password without re-creating."""
    with respx.mock(base_url=COUCH_URL) as mock:
        # Ensure passwords DB exists
        mock.put("/livesync-passwords").respond(412, json={"error": "file_exists"})
        # Stored password found
        mock.get("/livesync-passwords/pwd:alice@co.com").respond(
            200, json={"_id": "pwd:alice@co.com", "password": "stored-pw-123"},
        )

        password = await couch.ensure_user("alice@co.com")
        assert password == "stored-pw-123"
        # Should NOT have touched _users at all
        assert not any("_users" in str(c.request.url) for c in mock.calls)


# ── create_database ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_database(couch):
    with respx.mock(base_url=COUCH_URL) as mock:
        mock.put("/my-vault").respond(201, json={"ok": True})

        await couch.create_database("my-vault")
        assert mock.calls[-1].request.method == "PUT"


@pytest.mark.asyncio
async def test_create_database_already_exists(couch):
    """Creating an existing database should not raise (idempotent)."""
    with respx.mock(base_url=COUCH_URL) as mock:
        mock.put("/my-vault").respond(412, json={"error": "file_exists"})

        # Should not raise
        await couch.create_database("my-vault")


# ── set_security ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_security(couch):
    with respx.mock(base_url=COUCH_URL) as mock:
        mock.put("/my-vault/_security").respond(200, json={"ok": True})

        await couch.set_security(
            "my-vault",
            admin_names=["alice@co.com"],
            admin_roles=["livesync-admin"],
            member_names=["alice@co.com", "admin"],
            member_roles=["team-eng"],
        )

        import json
        body = json.loads(mock.calls[-1].request.content)
        assert body["admins"]["names"] == ["alice@co.com"]
        assert body["admins"]["roles"] == ["livesync-admin"]
        assert body["members"]["names"] == ["alice@co.com", "admin"]
        assert body["members"]["roles"] == ["team-eng"]


# ── registry CRUD ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_put_and_get_registry_doc(couch):
    """Store a vault doc in the registry and retrieve all docs."""
    vault_doc = {
        "_id": "vault:team-wiki",
        "name": "team-wiki",
        "owner": "alice@co.com",
        "members": ["alice@co.com"],
        "groups": [],
        "encrypted_only": False,
    }
    with respx.mock(base_url=COUCH_URL) as mock:
        # GET existing doc (not found — new doc)
        mock.get("/livesync-registry/vault:team-wiki").respond(404)
        # PUT the doc
        mock.put("/livesync-registry/vault:team-wiki").respond(
            201, json={"ok": True, "rev": "1-abc"}
        )
        await couch.put_registry_doc(vault_doc)

        # GET all docs
        mock.get("/livesync-registry/_all_docs").respond(
            200,
            json={
                "rows": [
                    {"id": "vault:team-wiki", "doc": vault_doc}
                ]
            },
        )
        docs = await couch.get_registry()
        assert len(docs) >= 1
        assert docs[0]["name"] == "team-wiki"


@pytest.mark.asyncio
async def test_get_user_vaults_filters_by_email_and_groups(couch):
    """get_user_vaults returns only vaults the user owns, is a member of,
    or belongs to via group membership."""
    all_vaults = [
        {"_id": "vault:alice-private", "name": "alice-private", "owner": "alice@co.com",
         "members": ["alice@co.com"], "groups": [], "encrypted_only": False},
        {"_id": "vault:team-eng", "name": "team-eng", "owner": "bob@co.com",
         "members": ["bob@co.com"], "groups": ["eng"], "encrypted_only": False},
        {"_id": "vault:bob-private", "name": "bob-private", "owner": "bob@co.com",
         "members": ["bob@co.com"], "groups": [], "encrypted_only": False},
    ]
    with respx.mock(base_url=COUCH_URL) as mock:
        mock.get("/livesync-registry/_all_docs").respond(
            200,
            json={"rows": [{"id": v["_id"], "doc": v} for v in all_vaults]},
        )

        # Alice is in the "eng" group → sees her own vault + team-eng
        vaults = await couch.get_user_vaults("alice@co.com", ["eng"])
        names = [v["name"] for v in vaults]
        assert "alice-private" in names
        assert "team-eng" in names
        assert "bob-private" not in names


# ── passphrase storage ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_and_get_passphrase(couch):
    with respx.mock(base_url=COUCH_URL) as mock:
        # GET existing (not found — new doc)
        mock.get("/livesync-passphrases/team-wiki").respond(404)
        # Store
        mock.put("/livesync-passphrases/team-wiki").respond(
            201, json={"ok": True, "rev": "1-abc"}
        )
        await couch.store_passphrase("team-wiki", "my-secret-passphrase")

        # Retrieve (now mock the GET to return the stored doc)
        mock.get("/livesync-passphrases/team-wiki").respond(
            200,
            json={"_id": "team-wiki", "passphrase": "my-secret-passphrase", "_rev": "1-abc"},
        )
        result = await couch.get_passphrase("team-wiki")
        assert result == "my-secret-passphrase"
