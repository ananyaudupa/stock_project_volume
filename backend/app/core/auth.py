"""Single-viewer password login.

The site is for one person, so there are no user accounts: one password (APP_PASSWORD) is
exchanged for an HttpOnly session cookie signed with a key derived from that password.
Changing the password therefore logs every existing session out.
"""

import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import ApiError

COOKIE_NAME = "scanner_session"
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300

_failures: dict[str, deque] = defaultdict(deque)


def _key(password: str) -> bytes:
    return hashlib.sha256(b"nse-scanner-session-v1:" + password.encode()).digest()


def make_token(password: str, ttl_seconds: int, now: float | None = None) -> str:
    expires = int((now or time.time()) + ttl_seconds)
    sig = hmac.new(_key(password), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def token_is_valid(token: str | None, password: str, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires_s, sig = token.split(".", 1)
    if not expires_s.isdigit() or int(expires_s) < (now or time.time()):
        return False
    expected = hmac.new(_key(password), expires_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def password_matches(given: str, password: str) -> bool:
    return hmac.compare_digest(given.encode(), password.encode())


def check_lockout(client: str, now: float | None = None) -> None:
    now = now or time.time()
    q = _failures[client]
    while q and q[0] < now - LOCKOUT_SECONDS:
        q.popleft()
    if len(q) >= MAX_FAILURES:
        raise ApiError(429, "too_many_attempts", "Too many wrong passwords. Please wait 5 minutes and try again.")


def record_failure(client: str, now: float | None = None) -> None:
    _failures[client].append(now or time.time())


def clear_failures(client: str) -> None:
    _failures.pop(client, None)


def require_login(request: Request, settings: Settings = Depends(get_settings)) -> None:
    if not settings.app_password:
        return  # development mode without a password
    if not token_is_valid(request.cookies.get(COOKIE_NAME), settings.app_password):
        raise ApiError(401, "login_required", "Please enter the password to continue.")
