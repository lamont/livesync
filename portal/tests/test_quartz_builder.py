"""Tests for the Quartz builder's config templating (portal/app/quartz_builder.py)."""

from unittest.mock import AsyncMock

import pytest

from app import quartz_builder
from app.quartz_builder import QuartzBuilder


@pytest.fixture
def builder():
    return QuartzBuilder(couch=AsyncMock())


@pytest.fixture
def quartz_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(quartz_builder, "QUARTZ_DIR", str(tmp_path))
    return tmp_path


TEMPLATE = """\
configuration:
  pageTitle: __VAULT_NAME__
  enableSPA: true
"""


def test_patch_writes_config_from_template(builder, quartz_dir):
    (quartz_dir / "quartz.config.template.yaml").write_text(TEMPLATE)

    builder._patch_quartz_config("obsidian_admin_wiki")

    config = (quartz_dir / "quartz.config.yaml").read_text()
    assert "pageTitle: obsidian_admin_wiki" in config
    assert "__VAULT_NAME__" not in config


def test_patch_is_repeatable_across_vaults(builder, quartz_dir):
    (quartz_dir / "quartz.config.template.yaml").write_text(TEMPLATE)

    builder._patch_quartz_config("obsidian_alice_notes")
    builder._patch_quartz_config("obsidian_bob_notes")

    config = (quartz_dir / "quartz.config.yaml").read_text()
    assert "pageTitle: obsidian_bob_notes" in config
    assert "obsidian_alice_notes" not in config


def test_patch_noop_without_template(builder, quartz_dir):
    builder._patch_quartz_config("obsidian_admin_wiki")

    assert not (quartz_dir / "quartz.config.yaml").exists()
