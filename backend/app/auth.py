from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeSerializer, BadSignature

from .settings import settings

COOKIE_NAME = "glh_auth"

def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.GLH_SECRET_KEY, salt="glh-timer-auth")

@dataclass
class CurrentUser:
    id: int
    username: str
    role: str  # "admin" | "organizer"
    race_id: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_organizer(self) -> bool:
        return self.role == "organizer"

def set_login_cookie(request: Request, *, user_id: int, username: str, role: str, race_id: Optional[str]) -> None:
    token = _serializer().dumps({"id": user_id, "u": username, "r": role, "race_id": race_id})
    request.state._set_auth_cookie = token

def clear_login_cookie(request: Request) -> None:
    request.state._clear_auth_cookie = True

def get_current_user(request: Request) -> Optional[CurrentUser]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw)
        return CurrentUser(
            id=int(data["id"]),
            username=str(data.get("u") or ""),
            role=str(data.get("r") or ""),
            race_id=data.get("race_id"),
        )
    except (BadSignature, Exception):
        return None

def staff_required(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    if user.role not in ("admin", "organizer"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return user

def admin_required(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user

def assert_can_access_race(user: CurrentUser, race_id: str) -> None:
    # Admin can access everything; organizers only their assigned race
    if user.role == "admin":
        return
    if user.role == "organizer" and user.race_id == race_id:
        return
    raise HTTPException(status_code=403, detail="Not allowed for this race")

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class AuthCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        token = getattr(request.state, "_set_auth_cookie", None)
        if token:
            response.set_cookie(
                COOKIE_NAME,
                token,
                httponly=True,
                samesite="lax",
                secure=False,  # set True behind HTTPS
                max_age=60 * 60 * 12,
            )
        if getattr(request.state, "_clear_auth_cookie", False):
            response.delete_cookie(COOKIE_NAME)
        return response
