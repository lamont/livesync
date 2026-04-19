"""Vault API routes."""

import os

from fastapi import APIRouter, HTTPException, Request

from ..couch import CouchClient
from ..models import VaultCreate, VaultInfo
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


@router.get("/vaults/{name}/setup-uri")
async def get_setup_uri(name: str, request: Request):
    user = request.state.user
    svc = get_vault_service()
    result = await svc.get_setup_uri(name, user.email)
    return result
