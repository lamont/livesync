from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def home(request: Request):
    user = request.state.user
    return {
        "user": user.email,
        "groups": user.groups,
        "is_admin": user.is_admin,
    }
