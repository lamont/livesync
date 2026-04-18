"""JWT authentication middleware.

In production, the ALB sets the ``x-amzn-oidc-data`` header with a signed JWT
containing the user's email and Okta groups.  For local development, use
``scripts/fake-jwt.py`` to generate a test token signed with JWT_SIGNING_KEY.
"""

import os

from fastapi import Request
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .models import User

ADMIN_GROUP = "livesync-admin"

# Header name matches what AWS ALB sets after OIDC authentication.
OIDC_HEADER = "x-amzn-oidc-data"

# For local dev, tokens are signed with a symmetric key.  In production with
# ALB OIDC, the JWT is signed by AWS and verified against the ALB's public key.
# We accept both HS256 (local) and RS256/ES256 (ALB) — jose handles this via
# the algorithms list.  When running behind a real ALB the JWT is already
# verified by the load balancer, so we can also accept unverified tokens by
# setting JWT_SKIP_VERIFY=true.
JWT_SIGNING_KEY = os.environ.get("JWT_SIGNING_KEY", "dev-secret-key")
JWT_SKIP_VERIFY = os.environ.get("JWT_SKIP_VERIFY", "").lower() in ("1", "true")
JWT_ALGORITHMS = ["HS256", "RS256", "ES256"]

# Paths that don't require authentication.
PUBLIC_PATHS = {"/healthz"}


def _decode_token(token: str) -> dict:
    if JWT_SKIP_VERIFY:
        return jwt.get_unverified_claims(token)
    return jwt.decode(token, JWT_SIGNING_KEY, algorithms=JWT_ALGORITHMS)


def _user_from_claims(claims: dict) -> User:
    email = claims.get("email", "")
    # Okta groups may come via "custom:groups" or "groups" depending on
    # the OIDC provider configuration.
    groups = claims.get("custom:groups", claims.get("groups", []))
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]
    return User(
        email=email,
        groups=groups,
        is_admin=ADMIN_GROUP in groups,
    )


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token = request.headers.get(OIDC_HEADER)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Missing {OIDC_HEADER} header"},
            )

        try:
            claims = _decode_token(token)
        except JWTError as exc:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Invalid token: {exc}"},
            )

        request.state.user = _user_from_claims(claims)
        return await call_next(request)
