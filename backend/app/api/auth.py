from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core import auth
from app.core.config import Settings, get_settings
from app.core.errors import ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _client(request: Request) -> str:
    # Behind a proxy (Render) the real client is the first X-Forwarded-For entry.
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


@router.get("/status")
def status(request: Request, settings: Settings = Depends(get_settings)):
    required = bool(settings.app_password)
    logged_in = not required or auth.token_is_valid(request.cookies.get(auth.COOKIE_NAME), settings.app_password)
    return {"auth_required": required, "logged_in": logged_in}


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, settings: Settings = Depends(get_settings)):
    if not settings.app_password:
        return {"logged_in": True}
    client = _client(request)
    auth.check_lockout(client)
    if not auth.password_matches(body.password, settings.app_password):
        auth.record_failure(client)
        raise ApiError(401, "wrong_password", "That password is not correct.")
    auth.clear_failures(client)
    ttl = settings.session_days * 86400
    response.set_cookie(
        auth.COOKIE_NAME, auth.make_token(settings.app_password, ttl), max_age=ttl, httponly=True,
        secure=settings.app_env == "production", samesite="lax", path="/",
    )
    return {"logged_in": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"logged_in": False}
