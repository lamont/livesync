"""Vault lifecycle management."""

import re
import secrets

from .couch import CouchClient
from .models import VaultInfo

# CouchDB requires lowercase database names starting with a letter,
# containing only [a-z0-9_-].
_VALID_VAULT_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")

# Admin CouchDB user that gets added to every vault's _security
ADMIN_USER = "admin"
ADMIN_ROLE = "livesync-admin"


async def generate_setup_uri(
    couch_url: str,
    username: str,
    password: str,
    database: str,
    passphrase: str,
) -> dict:
    """Generate an Obsidian LiveSync Setup URI.

    Returns ``{"setup_uri": "obsidian://...", "uri_passphrase": "word-word"}``.

    Shells out to the upstream generate_setupuri.ts Deno script to guarantee
    encryption compatibility with the Obsidian plugin.  Falls back to a
    placeholder if Deno is not available (e.g. in unit tests).
    """
    import asyncio
    import os

    script = os.environ.get("SETUP_URI_SCRIPT", "/scripts/generate_setupuri.ts")
    env = {
        **os.environ,
        "hostname": couch_url,
        "username": username,
        "password": password,
        "database": database,
        "passphrase": passphrase,
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            "deno", "-A", script,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode()
        uri = ""
        uri_passphrase = ""
        for line in output.splitlines():
            if line.startswith("obsidian://setuplivesync?"):
                uri = line.strip()
            if "passphrase" in line.lower() and ":" in line:
                # Line like "Your passphrase of Setup-URI is:  autumn-river"
                uri_passphrase = line.split(":", 1)[1].strip()
        if not uri:
            raise RuntimeError(f"No setup URI in output: {output} {stderr.decode()}")
        return {"setup_uri": uri, "uri_passphrase": uri_passphrase}
    except FileNotFoundError:
        # Deno not installed — return a placeholder for testing
        return {
            "setup_uri": f"obsidian://setuplivesync?settings=placeholder-{database}",
            "uri_passphrase": "test-placeholder",
        }


class VaultService:
    """Orchestrates vault creation, listing, sharing, and Setup URI generation."""

    def __init__(self, couch: CouchClient, external_couch_url: str | None = None):
        self.couch = couch
        # URL that end-user clients (Obsidian desktop, agents) use to reach
        # CouchDB.  Defaults to couch.base_url but should be overridden in
        # docker-compose (localhost:5984) vs K8s (ALB hostname).
        self.external_couch_url = external_couch_url or couch.base_url

    async def provision_user(self, email: str) -> str:
        """Ensure a CouchDB user exists for this email. Returns the password."""
        return await self.couch.ensure_user(email)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _vault_info_from_doc(doc: dict) -> VaultInfo:
        """Convert a registry doc to VaultInfo."""
        return VaultInfo(
            name=doc["name"],
            owner=doc["owner"],
            members=doc.get("members", []),
            groups=doc.get("groups", []),
            encrypted_only=doc.get("encrypted_only", False),
        )

    async def _sync_security(self, vault_name: str, doc: dict) -> None:
        """Derive and apply CouchDB _security from a registry doc."""
        owner = doc["owner"]
        members = doc.get("members", [])
        groups = doc.get("groups", [])
        await self.couch.set_security(
            vault_name,
            admin_names=[owner],
            admin_roles=[ADMIN_ROLE],
            member_names=list(set(members + [ADMIN_USER])),
            member_roles=groups,
        )

    # ── Vault CRUD ──────────────────────────────────────────────────────────

    async def create_vault(
        self, owner_email: str, name: str, *, encrypted_only: bool = False
    ) -> VaultInfo:
        """Create a new vault: CouchDB database + security + registry + passphrase."""
        # 0a. Validate name (CouchDB requires lowercase)
        if not _VALID_VAULT_NAME.match(name):
            raise ValueError(
                f"Invalid vault name '{name}': must start with a lowercase letter "
                "and contain only lowercase letters, numbers, hyphens, and underscores"
            )

        # 0b. Check for duplicate name
        existing = await self.couch.get_registry()
        if any(d.get("name") == name for d in existing):
            raise ValueError(f"Vault '{name}' already exists")

        # 1. Create the CouchDB database
        await self.couch.create_database(name)

        # 3. Generate and store E2EE passphrase
        passphrase = secrets.token_urlsafe(32)
        await self.couch.store_passphrase(name, passphrase)

        # 4. Write registry doc
        registry_doc = {
            "_id": f"vault:{name}",
            "name": name,
            "owner": owner_email,
            "members": [owner_email],
            "groups": [],
            "encrypted_only": encrypted_only,
        }
        await self.couch.put_registry_doc(registry_doc)

        # 2. Set per-database security (derived from registry doc)
        await self._sync_security(name, registry_doc)

        return self._vault_info_from_doc(registry_doc)

    async def list_vaults_for_user(
        self, email: str, groups: list[str]
    ) -> list[VaultInfo]:
        """Return vaults visible to this user."""
        docs = await self.couch.get_user_vaults(email, groups)
        return [self._vault_info_from_doc(d) for d in docs]

    async def get_vault(self, name: str) -> VaultInfo | None:
        """Look up a single vault by name."""
        doc = await self.couch.get_registry_doc(name)
        if doc is None:
            return None
        return self._vault_info_from_doc(doc)

    async def list_all_vaults(self) -> list[VaultInfo]:
        """Return all vaults (for admin dashboard)."""
        docs = await self.couch.get_registry()
        return [self._vault_info_from_doc(d) for d in docs]

    async def update_vault(
        self, name: str, *, encrypted_only: bool | None = None
    ) -> VaultInfo:
        """Update vault settings.  Currently supports toggling encrypted_only."""
        doc = await self.couch.get_registry_doc(name)
        if doc is None:
            raise ValueError(f"Vault '{name}' not found")

        if encrypted_only is not None:
            doc["encrypted_only"] = encrypted_only

        await self.couch.put_registry_doc(doc)
        return self._vault_info_from_doc(doc)

    # ── Sharing ─────────────────────────────────────────────────────────────

    async def share_vault(self, vault_name: str, email: str) -> VaultInfo:
        """Add a user to a vault's members.  Updates registry + CouchDB security."""
        doc = await self.couch.get_registry_doc(vault_name)
        if doc is None:
            raise ValueError(f"Vault '{vault_name}' not found")

        members = doc.get("members", [])
        if email in members:
            return self._vault_info_from_doc(doc)

        members.append(email)
        doc["members"] = members
        await self.couch.put_registry_doc(doc)

        # Ensure the new member has CouchDB credentials
        await self.couch.ensure_user(email)

        # Re-derive _security from the updated registry doc
        await self._sync_security(vault_name, doc)

        return self._vault_info_from_doc(doc)

    async def unshare_vault(self, vault_name: str, email: str) -> VaultInfo:
        """Remove a user from a vault's members."""
        doc = await self.couch.get_registry_doc(vault_name)
        if doc is None:
            raise ValueError(f"Vault '{vault_name}' not found")

        if email == doc.get("owner"):
            raise ValueError("Cannot remove the vault owner")

        members = doc.get("members", [])
        if email not in members:
            return self._vault_info_from_doc(doc)

        members.remove(email)
        doc["members"] = members
        await self.couch.put_registry_doc(doc)

        await self._sync_security(vault_name, doc)

        return self._vault_info_from_doc(doc)

    async def get_setup_uri(self, vault_name: str, email: str) -> dict:
        """Generate a Setup URI for a user to connect to a vault.

        Returns ``{"setup_uri": "obsidian://...", "uri_passphrase": "word-word"}``.
        """
        passphrase = await self.couch.get_passphrase(vault_name)
        password = await self.couch.ensure_user(email, reset_password=True)
        return await generate_setup_uri(
            couch_url=self.external_couch_url,
            username=email,
            password=password,
            database=vault_name,
            passphrase=passphrase,
        )
