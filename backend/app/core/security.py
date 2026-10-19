"""Admin authentication via a shared API key header. Admin endpoints are disabled when no key is configured."""

import hmac

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.core.errors import ApiError


def require_admin(x_admin_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> None:
    expected = settings.admin_api_key
    if not expected:
        raise ApiError(403, "admin_disabled", "Admin endpoints are disabled (ADMIN_API_KEY is not configured)")
    if not x_admin_key or not hmac.compare_digest(x_admin_key.encode(), expected.encode()):
        raise ApiError(401, "unauthorized", "Missing or invalid admin credentials")
