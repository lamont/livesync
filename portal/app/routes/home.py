from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from .api import get_vault_service

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
async def home(request: Request):
    user = request.state.user
    svc = get_vault_service()
    vaults = await svc.list_vaults_for_user(user.email, user.groups)
    return templates.TemplateResponse(
        request, name="home.html", context={"user": user, "vaults": vaults},
    )
