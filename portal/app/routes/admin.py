"""Admin dashboard route."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from .api import get_vault_service

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/admin/")
async def admin_dashboard(request: Request):
    user = request.state.user
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    svc = get_vault_service()
    vaults = await svc.list_all_vaults()
    return templates.TemplateResponse(
        request, name="admin.html", context={"user": user, "vaults": vaults},
    )
