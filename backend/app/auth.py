from __future__ import annotations
from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeSerializer, BadSignature

from .settings import settings

_cookie_name = "glh_admin"

def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.GLH_SECRET_KEY, salt="glh-timer")

def login_admin(request: Request, username: str, password: str) -> bool:
    if username != settings.GLH_ADMIN_USERNAME or password != settings.GLH_ADMIN_PASSWORD:
        return False
    token = _serializer().dumps({"u": username})
    # Set cookie on response is done by middleware pattern below:
    request.state._set_admin_cookie = token
    return True

def logout_admin(request: Request) -> None:
    request.state._clear_admin_cookie = True

def get_current_admin(request: Request):
    token = request.cookies.get(_cookie_name)
    if not token:
        return None
    try:
        data = _serializer().loads(token)
        return data.get("u")
    except BadSignature:
        return None

def admin_required(admin=Depends(get_current_admin)):
    if not admin:
        raise HTTPException(status_code=401, detail="Admin login required")
    return admin

# Cookie middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class AdminCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        token = getattr(request.state, "_set_admin_cookie", None)
        if token:
            response.set_cookie(
                _cookie_name,
                token,
                httponly=True,
                samesite="lax",
                secure=False,  # set True when behind HTTPS later
                max_age=60 * 60 * 12,
            )
        if getattr(request.state, "_clear_admin_cookie", False):
            response.delete_cookie(_cookie_name)
        return response
