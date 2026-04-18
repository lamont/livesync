"""Authentication middleware with two modes.

**oidc** (AUTH_MODE=oidc, default in K8s):
    The ALB sets ``x-amzn-oidc-data`` with a signed JWT containing the user's
    email and Okta groups.  The ``scripts/fake-jwt.py`` helper generates
    compatible tokens for curl-based testing in either mode.

**local** (AUTH_MODE=local, default in docker-compose):
    HTTP Basic Auth validated against a YAML users file.  The browser shows a
    native login dialog — no login form needed.  The users file is a simple
    list::

        # users.yaml
        - email: alice@example.com
          password: changeme
          groups: [livesync-admin]
        - email: bob@example.com
          password: changeme
          groups: [eng]
"""

import base64
import os
import secrets
from pathlib import Path

import yaml
from fastapi import Request
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from .models import User

ADMIN_GROUP = "livesync-admin"

# ── Mode selection ───────────────────────────────────────────────────────────
AUTH_MODE = os.environ.get("AUTH_MODE", "local")  # "oidc" or "local"

# ── OIDC settings ────────────────────────────────────────────────────────────
OIDC_HEADER = "x-amzn-oidc-data"
JWT_SIGNING_KEY = os.environ.get("JWT_SIGNING_KEY", "dev-secret-key")
JWT_SKIP_VERIFY = os.environ.get("JWT_SKIP_VERIFY", "").lower() in ("1", "true")
JWT_ALGORITHMS = ["HS256", "RS256", "ES256"]

# ── Local auth settings ─────────────────────────────────────────────────────
USERS_FILE = os.environ.get("USERS_FILE", "/app/users.yaml")

# Paths that never require authentication.
PUBLIC_PATHS = {"/healthz"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _decode_token(token: str) -> dict:
    if JWT_SKIP_VERIFY:
        return jwt.get_unverified_claims(token)
    return jwt.decode(token, JWT_SIGNING_KEY, algorithms=JWT_ALGORITHMS)


def _user_from_claims(claims: dict) -> User:
    email = claims.get("email", "")
    groups = claims.get("custom:groups", claims.get("groups", []))
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]
    return User(
        email=email,
        groups=groups,
        is_admin=ADMIN_GROUP in groups,
    )


def _load_users_file() -> list[dict]:
    """Load and cache the local users file.  Re-reads on every call so edits
    take effect without restarting the portal."""
    path = Path(USERS_FILE)
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    if isinstance(data, list):
        return data
    return []


def _authenticate_basic(auth_header: str) -> User | None:
    """Validate an HTTP Basic Auth header against the local users file."""
    try:
        scheme, encoded = auth_header.split(" ", 1)
        if scheme.lower() != "basic":
            return None
        decoded = base64.b64decode(encoded).decode("utf-8")
        email, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return None

    for entry in _load_users_file():
        if entry.get("email") == email:
            stored = entry.get("password", "")
            if secrets.compare_digest(str(stored), password):
                groups = entry.get("groups", [])
                if isinstance(groups, str):
                    groups = [g.strip() for g in groups.split(",") if g.strip()]
                return User(
                    email=email,
                    groups=groups,
                    is_admin=ADMIN_GROUP in groups,
                )
            return None  # wrong password
    return None  # user not found


def _basic_auth_challenge() -> Response:
    return Response(
        status_code=401,
        content="Unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="LiveSync Portal"'},
    )


# ── Middleware ───────────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # In either mode, accept x-amzn-oidc-data if present (allows
        # fake-jwt.py testing regardless of AUTH_MODE).
        oidc_token = request.headers.get(OIDC_HEADER)
        if oidc_token:
            try:
                claims = _decode_token(oidc_token)
                request.state.user = _user_from_claims(claims)
                return await call_next(request)
            except JWTError as exc:
                return JSONResponse(
                    status_code=401,
                    content={"detail": f"Invalid token: {exc}"},
                )

        if AUTH_MODE == "local":
            auth_header = request.headers.get("authorization")
            if not auth_header:
                return _basic_auth_challenge()

            user = _authenticate_basic(auth_header)
            if user is None:
                return _basic_auth_challenge()

            request.state.user = user
            return await call_next(request)

        # OIDC mode: no OIDC header and no fallback → 401
        return JSONResponse(
            status_code=401,
            content={"detail": f"Missing {OIDC_HEADER} header"},
        )
