"""Tests for vault service business logic (portal/app/vault_service.py).

Mocks the CouchClient to test orchestration logic without CouchDB.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.couch import CouchClient
from app.models import VaultInfo
from app.vault_service import VaultService, make_vault_db_name, normalize_username


@pytest.fixture
def mock_couch():
    couch = AsyncMock(spec=CouchClient)
    couch.base_url = "http://couchdb:5984"
    return couch


@pytest.fixture
def service(mock_couch):
    return VaultService(mock_couch)


# ── normalize_username ──────────────────────────────────────────────────────

def test_normalize_simple_email():
    assert normalize_username("admin@localhost") == "admin"


def test_normalize_dotted_email():
    assert normalize_username("john.doe@company.com") == "john_doe"


def test_normalize_plus_email():
    assert normalize_username("jane+test@company.com") == "jane_test"


def test_normalize_uppercase_email():
    assert normalize_username("Admin@Localhost") == "admin"


def test_normalize_consecutive_special_chars():
    assert normalize_username("a..b@x.com") == "a_b"


# ── make_vault_db_name ──────────────────────────────────────────────────────

def test_make_vault_db_name():
    assert make_vault_db_name("admin@localhost", "wiki") == "obsidian_admin_wiki"


def test_make_vault_db_name_dotted():
    assert make_vault_db_name("john.doe@co.com", "notes") == "obsidian_john_doe_notes"


# ── provision_user ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provision_user_calls_ensure_user(service, mock_couch):
    mock_couch.ensure_user.return_value = "generated-password-123"

    password = await service.provision_user("alice@co.com")

    mock_couch.ensure_user.assert_called_once_with("alice@co.com")
    assert password == "generated-password-123"


# ── create_vault ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_vault_orchestrates_all_steps(service, mock_couch):
    """create_vault should: create DB, set security, store passphrase,
    write registry doc, and return VaultInfo."""
    mock_couch.get_registry.return_value = []
    mock_couch.ensure_user.return_value = "pw123"

    vault = await service.create_vault("alice@co.com", "myvault")

    assert isinstance(vault, VaultInfo)
    assert vault.name == "obsidian_alice_myvault"
    assert vault.owner == "alice@co.com"
    assert "alice@co.com" in vault.members

    # Verify all CouchDB operations were called
    mock_couch.create_database.assert_called_once_with("obsidian_alice_myvault")
    mock_couch.set_security.assert_called_once()
    mock_couch.store_passphrase.assert_called_once()
    mock_couch.put_registry_doc.assert_called_once()

    # Check security was set with owner as admin
    sec_call = mock_couch.set_security.call_args
    assert "alice@co.com" in sec_call.kwargs.get("admin_names", sec_call.args[1] if len(sec_call.args) > 1 else [])

    # Check passphrase was stored (we don't care what it is, just that it's non-empty)
    pp_call = mock_couch.store_passphrase.call_args
    assert pp_call.args[0] == "obsidian_alice_myvault"  # vault name
    assert len(pp_call.args[1]) > 0  # passphrase is non-empty


@pytest.mark.asyncio
async def test_create_vault_rejects_duplicate_name(service, mock_couch):
    """Creating a vault with an existing name should raise."""
    mock_couch.get_registry.return_value = [
        {"name": "obsidian_bob_taken", "owner": "bob@co.com", "members": ["bob@co.com"],
         "groups": [], "encrypted_only": False},
    ]

    with pytest.raises(ValueError, match="already exists"):
        await service.create_vault("bob@co.com", "taken")

    # Should NOT have created the database
    mock_couch.create_database.assert_not_called()


@pytest.mark.asyncio
async def test_create_vault_rejects_invalid_suffix(service, mock_couch):
    """Suffix with invalid characters should raise."""
    mock_couch.get_registry.return_value = []

    with pytest.raises(ValueError, match="Invalid vault name"):
        await service.create_vault("alice@co.com", "BAD-NAME")


@pytest.mark.asyncio
async def test_create_vault_encrypted_only(service, mock_couch):
    mock_couch.get_registry.return_value = []
    mock_couch.ensure_user.return_value = "pw123"

    vault = await service.create_vault("alice@co.com", "secret", encrypted_only=True)

    assert vault.encrypted_only is True

    # Registry doc should have encrypted_only flag
    reg_call = mock_couch.put_registry_doc.call_args
    doc = reg_call.args[0]
    assert doc["encrypted_only"] is True


@pytest.mark.asyncio
async def test_create_vault_generates_passphrase(service, mock_couch):
    """Each vault gets a unique E2EE passphrase."""
    mock_couch.get_registry.return_value = []
    mock_couch.ensure_user.return_value = "pw"

    await service.create_vault("a@co.com", "vault1")
    pp1 = mock_couch.store_passphrase.call_args.args[1]

    mock_couch.reset_mock()
    mock_couch.get_registry.return_value = []
    await service.create_vault("a@co.com", "vault2")
    pp2 = mock_couch.store_passphrase.call_args.args[1]

    # Passphrases should be different (astronomically unlikely to collide)
    assert pp1 != pp2


# ── list_vaults_for_user ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_vaults_for_user(service, mock_couch):
    mock_couch.get_user_vaults.return_value = [
        {"name": "obsidian_alice_v1", "owner": "alice@co.com", "members": ["alice@co.com"],
         "groups": [], "encrypted_only": False},
        {"name": "obsidian_bob_v2", "owner": "bob@co.com", "members": ["bob@co.com", "alice@co.com"],
         "groups": [], "encrypted_only": False},
    ]

    vaults = await service.list_vaults_for_user("alice@co.com", ["eng"])

    assert len(vaults) == 2
    assert all(isinstance(v, VaultInfo) for v in vaults)
    assert vaults[0].name == "obsidian_alice_v1"
    mock_couch.get_user_vaults.assert_called_once_with("alice@co.com", ["eng"])


@pytest.mark.asyncio
async def test_list_vaults_empty(service, mock_couch):
    mock_couch.get_user_vaults.return_value = []

    vaults = await service.list_vaults_for_user("newuser@co.com", [])
    assert vaults == []


# ── get_vault ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_vault_exists(service, mock_couch):
    mock_couch.get_registry_doc.return_value = {
        "_id": "vault:obsidian_alice_wiki",
        "name": "obsidian_alice_wiki", "owner": "alice@co.com",
        "members": ["alice@co.com"],
        "groups": [], "encrypted_only": False,
    }

    vault = await service.get_vault("obsidian_alice_wiki")
    assert vault is not None
    assert vault.name == "obsidian_alice_wiki"
    mock_couch.get_registry_doc.assert_called_once_with("obsidian_alice_wiki")


@pytest.mark.asyncio
async def test_get_vault_not_found(service, mock_couch):
    mock_couch.get_registry_doc.return_value = None

    vault = await service.get_vault("nonexistent")
    assert vault is None


# ── get_setup_uri ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_setup_uri_returns_obsidian_uri(service, mock_couch):
    """get_setup_uri should return an obsidian://setuplivesync?... URI."""
    mock_couch.get_passphrase.return_value = "vault-e2ee-passphrase"
    mock_couch.ensure_user.return_value = "user-couch-password"

    # Mock the subprocess call to generate_setupuri.ts
    with patch("app.vault_service.generate_setup_uri") as mock_gen:
        mock_gen.return_value = {
            "setup_uri": "obsidian://setuplivesync?settings=encrypted-blob",
            "uri_passphrase": "autumn-river",
        }

        result = await service.get_setup_uri("obsidian_alice_wiki", "alice@co.com")

        assert result["setup_uri"].startswith("obsidian://setuplivesync?")
        assert result["uri_passphrase"] == "autumn-river"
        mock_couch.get_passphrase.assert_called_with("obsidian_alice_wiki")
        mock_couch.ensure_user.assert_called_with("alice@co.com", reset_password=True)


# ── update_vault ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_vault_encrypted_only(service, mock_couch):
    """update_vault should toggle encrypted_only and write registry doc."""
    mock_couch.get_registry_doc.return_value = {
        "_id": "vault:obsidian_alice_wiki",
        "name": "obsidian_alice_wiki", "owner": "alice@co.com",
        "members": ["alice@co.com"], "groups": [],
        "encrypted_only": False,
    }

    vault = await service.update_vault("obsidian_alice_wiki", encrypted_only=True)

    assert vault.encrypted_only is True
    doc = mock_couch.put_registry_doc.call_args.args[0]
    assert doc["encrypted_only"] is True


@pytest.mark.asyncio
async def test_update_vault_not_found(service, mock_couch):
    """update_vault should raise ValueError for missing vault."""
    mock_couch.get_registry_doc.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.update_vault("nonexistent", encrypted_only=True)
