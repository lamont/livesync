"""Welcome / first-login route."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .api import get_vault_service

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/welcome")
async def welcome(request: Request):
    user = request.state.user
    return templates.TemplateResponse(
        request, name="welcome.html", context={"user": user},
    )


@router.post("/welcome")
async def create_vault_form(
    request: Request,
    name: str = Form(...),
    encrypted_only: bool = Form(False),
):
    user = request.state.user
    svc = get_vault_service()
    try:
        await svc.create_vault(
            owner_email=user.email,
            name=name,
            encrypted_only=encrypted_only,
        )
        return RedirectResponse(url="/", status_code=303)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            name="welcome.html",
            context={"user": user, "error": str(exc)},
        )
