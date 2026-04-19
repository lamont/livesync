"""Vault lifecycle management."""

import secrets

from .couch import CouchClient
from .models import VaultInfo

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

    async def create_vault(
        self, owner_email: str, name: str, *, encrypted_only: bool = False
    ) -> VaultInfo:
        """Create a new vault: CouchDB database + security + registry + passphrase."""
        # 0. Check for duplicate name
        existing = await self.couch.get_registry()
        if any(d.get("name") == name for d in existing):
            raise ValueError(f"Vault '{name}' already exists")

        # 1. Create the CouchDB database
        await self.couch.create_database(name)

        # 2. Set per-database security
        await self.couch.set_security(
            name,
            admin_names=[owner_email],
            admin_roles=[ADMIN_ROLE],
            member_names=[owner_email, ADMIN_USER],
            member_roles=[],
        )

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

        return VaultInfo(
            name=name,
            owner=owner_email,
            members=[owner_email],
            groups=[],
            encrypted_only=encrypted_only,
        )

    async def list_vaults_for_user(
        self, email: str, groups: list[str]
    ) -> list[VaultInfo]:
        """Return vaults visible to this user."""
        docs = await self.couch.get_user_vaults(email, groups)
        return [
            VaultInfo(
                name=d["name"],
                owner=d["owner"],
                members=d.get("members", []),
                groups=d.get("groups", []),
                encrypted_only=d.get("encrypted_only", False),
            )
            for d in docs
        ]

    async def get_vault(self, name: str) -> VaultInfo | None:
        """Look up a single vault by name."""
        all_docs = await self.couch.get_registry()
        for d in all_docs:
            if d.get("name") == name:
                return VaultInfo(
                    name=d["name"],
                    owner=d["owner"],
                    members=d.get("members", []),
                    groups=d.get("groups", []),
                    encrypted_only=d.get("encrypted_only", False),
                )
        return None

    async def get_setup_uri(self, vault_name: str, email: str) -> dict:
        """Generate a Setup URI for a user to connect to a vault.

        Returns ``{"setup_uri": "obsidian://...", "uri_passphrase": "word-word"}``.
        """
        passphrase = await self.couch.get_passphrase(vault_name)
        password = await self.couch.ensure_user(email)
        return await generate_setup_uri(
            couch_url=self.external_couch_url,
            username=email,
            password=password,
            database=vault_name,
            passphrase=passphrase,
        )
