"""Vault viewer routes — serve per-vault Quartz static output with access checks."""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse

from .api import get_vault_service

router = APIRouter()

STATIC_DIR = Path(os.environ.get("STATIC_DIR", "/static"))


def _user_can_access(user, vault) -> bool:
    """Check if user has access to this vault."""
    if user.is_admin:
        return True
    if vault.owner == user.email:
        return True
    if user.email in vault.members:
        return True
    if set(user.groups) & set(vault.groups):
        return True
    return False


@router.get("/vaults/{name}/{path:path}")
async def serve_vault(name: str, path: str, request: Request):
    """Serve a Quartz-built static file for a vault, with access control."""
    user = request.state.user
    svc = get_vault_service()

    vault = await svc.get_vault(name)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")

    if not _user_can_access(user, vault):
        raise HTTPException(status_code=403, detail="Not a member of this vault")

    vault_static = STATIC_DIR / name
    if not vault_static.is_dir():
        raise HTTPException(status_code=404, detail="Vault not yet built")

    # Resolve the requested path
    if not path or path == "/":
        path = "index.html"

    file_path = (vault_static / path).resolve()

    # Prevent path traversal
    if not str(file_path).startswith(str(vault_static.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")

    if file_path.is_file():
        return FileResponse(file_path)

    # Try index.html for directory-style paths
    index = file_path / "index.html"
    if index.is_file():
        return FileResponse(index)

    raise HTTPException(status_code=404, detail="File not found")


@router.get("/vaults/{name}")
async def serve_vault_root(name: str, request: Request):
    """Redirect /vaults/{name} to /vaults/{name}/ for proper relative links."""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url=f"/vaults/{name}/", status_code=301)
