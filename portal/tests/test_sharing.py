"""Tests for vault sharing logic (share_vault / unshare_vault)."""

from unittest.mock import AsyncMock

import pytest

from app.couch import CouchClient
from app.models import VaultInfo
from app.vault_service import VaultService


def _make_registry_doc(name="team-wiki", owner="alice@co.com", members=None, groups=None):
    return {
        "_id": f"vault:{name}",
        "_rev": "1-abc",
        "name": name,
        "owner": owner,
        "members": members or [owner],
        "groups": groups or [],
        "encrypted_only": False,
    }


@pytest.fixture
def mock_couch():
    couch = AsyncMock(spec=CouchClient)
    couch.base_url = "http://couchdb:5984"
    return couch


@pytest.fixture
def service(mock_couch):
    return VaultService(mock_couch)


# ── share_vault ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_share_vault_adds_member(service, mock_couch):
    doc = _make_registry_doc()
    mock_couch.get_registry_doc.return_value = doc

    result = await service.share_vault("team-wiki", "bob@co.com")

    assert isinstance(result, VaultInfo)
    assert "bob@co.com" in result.members
    mock_couch.put_registry_doc.assert_called_once()
    mock_couch.ensure_user.assert_called_once_with("bob@co.com")
    mock_couch.set_security.assert_called_once()


@pytest.mark.asyncio
async def test_share_vault_idempotent(service, mock_couch):
    doc = _make_registry_doc(members=["alice@co.com", "bob@co.com"])
    mock_couch.get_registry_doc.return_value = doc

    result = await service.share_vault("team-wiki", "bob@co.com")

    assert "bob@co.com" in result.members
    # Should NOT update registry or security — already a member
    mock_couch.put_registry_doc.assert_not_called()
    mock_couch.set_security.assert_not_called()


@pytest.mark.asyncio
async def test_share_vault_not_found(service, mock_couch):
    mock_couch.get_registry_doc.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.share_vault("missing", "bob@co.com")


@pytest.mark.asyncio
async def test_share_vault_ensures_couchdb_user(service, mock_couch):
    doc = _make_registry_doc()
    mock_couch.get_registry_doc.return_value = doc

    await service.share_vault("team-wiki", "newuser@co.com")

    mock_couch.ensure_user.assert_called_once_with("newuser@co.com")


@pytest.mark.asyncio
async def test_share_vault_syncs_security(service, mock_couch):
    doc = _make_registry_doc()
    mock_couch.get_registry_doc.return_value = doc

    await service.share_vault("team-wiki", "bob@co.com")

    sec_call = mock_couch.set_security.call_args
    member_names = sec_call.kwargs["member_names"]
    assert "bob@co.com" in member_names
    assert "alice@co.com" in member_names
    assert "admin" in member_names


# ── unshare_vault ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unshare_vault_removes_member(service, mock_couch):
    doc = _make_registry_doc(members=["alice@co.com", "bob@co.com"])
    mock_couch.get_registry_doc.return_value = doc

    result = await service.unshare_vault("team-wiki", "bob@co.com")

    assert "bob@co.com" not in result.members
    mock_couch.put_registry_doc.assert_called_once()
    mock_couch.set_security.assert_called_once()


@pytest.mark.asyncio
async def test_unshare_vault_cannot_remove_owner(service, mock_couch):
    doc = _make_registry_doc()
    mock_couch.get_registry_doc.return_value = doc

    with pytest.raises(ValueError, match="Cannot remove the vault owner"):
        await service.unshare_vault("team-wiki", "alice@co.com")


@pytest.mark.asyncio
async def test_unshare_vault_idempotent(service, mock_couch):
    doc = _make_registry_doc(members=["alice@co.com"])
    mock_couch.get_registry_doc.return_value = doc

    result = await service.unshare_vault("team-wiki", "bob@co.com")

    assert "bob@co.com" not in result.members
    mock_couch.put_registry_doc.assert_not_called()
    mock_couch.set_security.assert_not_called()


@pytest.mark.asyncio
async def test_unshare_vault_not_found(service, mock_couch):
    mock_couch.get_registry_doc.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.unshare_vault("missing", "bob@co.com")


# ── list_all_vaults ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_all_vaults(service, mock_couch):
    mock_couch.get_registry.return_value = [
        _make_registry_doc(name="v1", owner="a@co.com"),
        _make_registry_doc(name="v2", owner="b@co.com"),
    ]

    vaults = await service.list_all_vaults()

    assert len(vaults) == 2
    assert all(isinstance(v, VaultInfo) for v in vaults)
    assert vaults[0].name == "v1"
    assert vaults[1].name == "v2"
