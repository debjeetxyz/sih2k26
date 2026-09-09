"""
JWT authentication + RBAC.

Real (not stubbed) implementation:
  - Tokens are signed/verified with HS256 using JWT_SECRET from the
    environment. The process refuses to start with no secret set, rather
    than silently falling back to something insecure.
  - Tokens are short-lived (JWT_EXPIRE_MINUTES, default 60) and carry a role
    claim mapped onto the Role enum below.
  - No external IdP — appropriate for a local, air-gapped deployment.

TODO (real user management): there's no user database yet, so token
issuance (see /auth/token in main.py) is a bootstrap-secret-gated dev
endpoint, not a real login flow. Replace with actual credential checking
against a local user store before this touches anything resembling
production. See main.py for that endpoint's full caveat.
"""

# pyright: reportMissingImports=false

import enum
import os
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, WebSocket
from jose import JWTError, jwt  # type: ignore[reportMissingImports]

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET is not set. Refusing to start with no signing key — "
        "set a long random value in .env (see .env.example)."
    )


class Role(str, enum.Enum):
    OPERATOR = "operator"  # pilot: monitoring + HUD + checklists
    PROPULSION_ENGINEER = (
        "propulsion_engineer"  # full access: history, injection, export
    )
    SYSTEM = "system"  # internal service-to-service (e.g. injector bridge)


def create_access_token(
    role: Role, subject: str, expires_minutes: int | None = None
) -> str:
    """Mint a signed JWT carrying a role claim. Used by /auth/token."""
    minutes = JWT_EXPIRE_MINUTES if expires_minutes is None else expires_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role.value,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode(token: str) -> Role | None:
    """Verify signature + expiry, then extract the role claim.

    Returns None on ANY failure (bad signature, expired, malformed, unknown
    role) — callers treat None as "unauthorized", never partially trusting
    a token that failed verification.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    try:
        return Role(payload.get("role"))
    except ValueError:
        return None


async def get_current_role(authorization: str | None = Header(default=None)) -> Role:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    role = _decode(token)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return role


async def validate_ws_token(websocket: WebSocket) -> Role | None:
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
    return _decode(token or "")
