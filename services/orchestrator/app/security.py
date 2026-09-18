from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from .config import settings


@dataclass
class RequestContext:
    user_id: str
    user_role: str


def _allowed_roles() -> set[str]:
    return {role.strip().lower() for role in settings.allowed_roles.split(",") if role.strip()}


async def get_request_context(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> RequestContext:
    if not settings.enforce_identity_headers:
        return RequestContext(user_id="system", user_role="admin")

    if not x_user_id or not x_user_role:
        raise HTTPException(status_code=401, detail="Missing identity headers: X-User-Id and X-User-Role")

    role = x_user_role.strip().lower()
    if role not in _allowed_roles():
        raise HTTPException(status_code=403, detail="User role not allowed for this platform")

    return RequestContext(user_id=x_user_id.strip(), user_role=role)
