"""
JWT authentication + RBAC stub.

Real implementation should:
  - Verify signature with a secret/key loaded from env (JWT_SECRET), never
    hardcoded.
  - Enforce short-lived tokens + refresh flow appropriate for a local,
    air-gapped deployment (no external IdP).
  - Map claims -> Role enum below.

This stub accepts a fixed dev token so the rest of the scaffold is runnable;
it MUST be replaced before anything resembling a real deployment.
"""

import enum
import os

from fastapi import Header, HTTPException, WebSocket

JWT_SECRET = os.getenv("JWT_SECRET", "")  # set via .env, never commit a real one


class Role(str, enum.Enum):
    OPERATOR = "operator"  # pilot: monitoring + HUD + checklists
    PROPULSION_ENGINEER = (
        "propulsion_engineer"  # full access: history, injection, export
    )
    SYSTEM = "system"  # internal service-to-service (e.g. injector bridge)


def _decode_stub(token: str) -> Role | None:
    """Placeholder decode. Swap for real JWT verification (e.g. python-jose)."""
    if not token:
        return None
    # TODO: replace with jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    #       and pull the role out of verified claims.
    mapping = {
        "dev-operator-token": Role.OPERATOR,
        "dev-engineer-token": Role.PROPULSION_ENGINEER,
        "dev-system-token": Role.SYSTEM,
    }
    return mapping.get(token)


async def get_current_role(authorization: str | None = Header(default=None)) -> Role:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    role = _decode_stub(token)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return role


async def validate_ws_token(websocket: WebSocket) -> Role | None:
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
    return _decode_stub(token or "")
