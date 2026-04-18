"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from app.models import User, VaultCreate, VaultInfo


def test_user_defaults():
    u = User(email="a@b.com")
    assert u.groups == []
    assert u.is_admin is False


def test_user_with_all_fields():
    u = User(email="a@b.com", groups=["eng"], is_admin=True)
    assert u.email == "a@b.com"
    assert u.groups == ["eng"]


def test_vault_create_defaults():
    v = VaultCreate(name="my-vault")
    assert v.encrypted_only is False


def test_vault_create_encrypted():
    v = VaultCreate(name="secret", encrypted_only=True)
    assert v.encrypted_only is True


def test_vault_create_requires_name():
    with pytest.raises(ValidationError):
        VaultCreate()


def test_vault_info_defaults():
    v = VaultInfo(name="v1", owner="alice@co.com")
    assert v.members == []
    assert v.groups == []
    assert v.encrypted_only is False
