"""Vault API routes."""

import os

from fastapi import APIRouter, HTTPException, Request

from ..couch import CouchClient
from ..models import MembersUpdate, VaultCreate, VaultInfo, VaultUpdate
from ..vault_service import VaultService

router = APIRouter(prefix="/api")

_vault_service: VaultService | None = None


def get_vault_service() -> VaultService:
    """Return the singleton VaultService, lazily created from env vars."""
    global _vault_service
    if _vault_service is None:
        couch = CouchClient(
            base_url=os.environ.get("COUCHDB_URI", "http://couchdb:5984"),
            admin_user=os.environ.get("COUCHDB_USER", "admin"),
            admin_password=os.environ.get("COUCHDB_PASSWORD", ""),
        )
        _vault_service = VaultService(
            couch,
            external_couch_url=os.environ.get("COUCHDB_EXTERNAL_URI"),
        )
    return _vault_service


def set_vault_service(svc: VaultService | None) -> None:
    """Override the vault service (for testing)."""
    global _vault_service
    _vault_service = svc


@router.post("/vaults", status_code=201, response_model=VaultInfo)
async def create_vault(body: VaultCreate, request: Request):
    user = request.state.user
    svc = get_vault_service()
    try:
        return await svc.create_vault(
            owner_email=user.email,
            name=body.name,
            encrypted_only=body.encrypted_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/vaults", response_model=list[VaultInfo])
async def list_vaults(request: Request):
    user = request.state.user
    svc = get_vault_service()
    return await svc.list_vaults_for_user(user.email, user.groups)


@router.get("/vaults/{name}", response_model=VaultInfo)
async def get_vault(name: str, request: Request):
    svc = get_vault_service()
    vault = await svc.get_vault(name)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    return vault


@router.patch("/vaults/{name}", response_model=VaultInfo)
async def update_vault(name: str, body: VaultUpdate, request: Request):
    user = request.state.user
    svc = get_vault_service()

    vault = await svc.get_vault(name)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    if vault.owner != user.email and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the vault owner can update settings")

    updates = body.model_dump(exclude_none=True)
    try:
        return await svc.update_vault(name, **updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/vaults/{name}/members", response_model=VaultInfo)
async def update_members(name: str, body: MembersUpdate, request: Request):
    user = request.state.user
    svc = get_vault_service()

    vault = await svc.get_vault(name)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    if vault.owner != user.email and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the vault owner can manage members")

    result = vault
    for email in body.add:
        try:
            result = await svc.share_vault(name, email)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    for email in body.remove:
        try:
            result = await svc.unshare_vault(name, email)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/vaults/{name}/agent", status_code=501)
async def trigger_agent(name: str, request: Request):
    user = request.state.user
    svc = get_vault_service()

    vault = await svc.get_vault(name)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")

    return {
        "detail": "Agent API not yet implemented.",
        "cli": f"docker compose run -e VAULT_NAME={name} -e INSTRUCTION='your prompt' agent-multi",
    }


@router.get("/vaults/{name}/setup-uri")
async def get_setup_uri(name: str, request: Request):
    user = request.state.user
    svc = get_vault_service()
    result = await svc.get_setup_uri(name, user.email)
    return result
