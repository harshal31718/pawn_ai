"""JWT authentication middleware.

Reads Authorization: Bearer <token> and sets request.state.user_id + request.state.email.
Skips /health and /auth/* (public endpoints).
Returns 401 JSON for protected routes with missing/invalid/expired tokens.
"""

import json

import jwt as pyjwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.jwt_utils import decode_token

_PUBLIC_PREFIXES = ("/health", "/auth/")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        token = auth[7:]
        try:
            payload = decode_token(token)
        except pyjwt.ExpiredSignatureError:
            return JSONResponse({"detail": "Token expired"}, status_code=401)
        except pyjwt.PyJWTError:
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        request.state.user_id = payload["sub"]
        request.state.email = payload.get("email", "")
        return await call_next(request)
