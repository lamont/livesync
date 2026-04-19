"""Async CouchDB admin client wrapping httpx."""

import json
import secrets

import httpx

# Registry and passphrase databases — created by couchdb-init.
REGISTRY_DB = "livesync-registry"
PASSPHRASES_DB = "livesync-passphrases"


class CouchClient:
    """Thin async wrapper around CouchDB's HTTP API."""

    def __init__(self, base_url: str, admin_user: str, admin_password: str):
        self.base_url = base_url.rstrip("/")
        self.auth = (admin_user, admin_password)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            auth=self.auth,
            timeout=10.0,
        )

    async def close(self):
        await self._http.aclose()

    # ── User management ──────────────────────────────────────────────────────

    async def ensure_user(self, email: str) -> str:
        """Ensure a CouchDB user exists for *email*.  Returns the password.

        If the user already exists we reset the password (since we don't store
        CouchDB passwords outside of CouchDB).  This is safe because the only
        consumer of the password is the Setup URI generator.
        """
        password = secrets.token_urlsafe(24)
        doc_id = f"org.couchdb.user:{email}"
        url = f"/_users/{doc_id}"

        # Check for existing user to get _rev (required for update)
        resp = await self._http.get(url)
        doc = {
            "_id": doc_id,
            "name": email,
            "password": password,
            "roles": [],
            "type": "user",
        }
        if resp.status_code == 200:
            doc["_rev"] = resp.json()["_rev"]

        await self._http.put(url, json=doc)
        return password

    # ── Database management ──────────────────────────────────────────────────

    async def create_database(self, name: str) -> None:
        """Create a CouchDB database.  Idempotent — ignores 'already exists'."""
        resp = await self._http.put(f"/{name}")
        # 201 = created, 412 = already exists — both are fine
        if resp.status_code not in (201, 412):
            resp.raise_for_status()

    async def set_security(
        self,
        db_name: str,
        *,
        admin_names: list[str] | None = None,
        admin_roles: list[str] | None = None,
        member_names: list[str] | None = None,
        member_roles: list[str] | None = None,
    ) -> None:
        """Set the _security object on a database."""
        doc = {
            "admins": {
                "names": admin_names or [],
                "roles": admin_roles or [],
            },
            "members": {
                "names": member_names or [],
                "roles": member_roles or [],
            },
        }
        resp = await self._http.put(f"/{db_name}/_security", json=doc)
        resp.raise_for_status()

    # ── Registry CRUD ────────────────────────────────────────────────────────

    async def get_registry(self) -> list[dict]:
        """Return all vault docs from the registry database."""
        resp = await self._http.get(
            f"/{REGISTRY_DB}/_all_docs",
            params={"include_docs": "true"},
        )
        resp.raise_for_status()
        return [row["doc"] for row in resp.json().get("rows", [])]

    async def put_registry_doc(self, doc: dict) -> None:
        """Create or update a vault doc in the registry."""
        doc_id = doc["_id"]
        # Get existing doc for _rev if it exists
        resp = await self._http.get(f"/{REGISTRY_DB}/{doc_id}")
        if resp.status_code == 200:
            doc["_rev"] = resp.json()["_rev"]
        resp = await self._http.put(f"/{REGISTRY_DB}/{doc_id}", json=doc)
        resp.raise_for_status()

    async def get_user_vaults(self, email: str, groups: list[str]) -> list[dict]:
        """Return vaults the user owns, is a member of, or has group access to."""
        all_docs = await self.get_registry()
        result = []
        groups_set = set(groups)
        for doc in all_docs:
            if doc.get("owner") == email:
                result.append(doc)
            elif email in doc.get("members", []):
                result.append(doc)
            elif groups_set & set(doc.get("groups", [])):
                result.append(doc)
        return result

    # ── Passphrase storage ───────────────────────────────────────────────────

    async def store_passphrase(self, vault_name: str, passphrase: str) -> None:
        """Store a vault's E2EE passphrase in the admin-only passphrases DB."""
        doc_id = vault_name
        doc = {"_id": doc_id, "passphrase": passphrase}
        # Get existing for _rev
        resp = await self._http.get(f"/{PASSPHRASES_DB}/{doc_id}")
        if resp.status_code == 200:
            doc["_rev"] = resp.json()["_rev"]
        resp = await self._http.put(f"/{PASSPHRASES_DB}/{doc_id}", json=doc)
        resp.raise_for_status()

    async def get_passphrase(self, vault_name: str) -> str:
        """Retrieve a vault's E2EE passphrase."""
        resp = await self._http.get(f"/{PASSPHRASES_DB}/{vault_name}")
        resp.raise_for_status()
        return resp.json()["passphrase"]
