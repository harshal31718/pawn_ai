"""Google OAuth2 authentication routes.

Flow:
  Frontend hits GET /auth/login → receives auth_url → redirects user to Google.
  Google redirects to GET /auth/callback?code=... → backend exchanges code,
  upserts user in Postgres, stores encrypted Drive tokens, issues JWT.
  Backend redirects to frontend /?token=<jwt>&user=<json>.
"""

import json
import os
import sys
from datetime import datetime, timezone

# Google may return scopes in a different order, or drop a scope the user did not
# grant via granular consent (e.g. drive.file). oauthlib treats any scope change as
# an error by default; relax that so the token exchange completes. Drive is mandatory
# for storage — if drive.file was declined, the request later fails clearly via
# require_drive_for_user()/412, not a silent fallback.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from google.auth.transport.requests import Request as GRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FRONTEND_URL, OAUTH_REDIRECT_URI
from app.core import login_rate_limiter
from app.core.admin import is_admin
from app.core.crypto import encrypt
from app.core.jwt_utils import create_token, decode_token
from app.core.password_utils import generate_password, hash_password, verify_password
from app.db.postgres_client import execute, fetchone

import jwt as pyjwt

router = APIRouter(prefix="/auth", tags=["auth"])

_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
]

# Frontend URL to redirect to after successful auth. _REDIRECT_URI must exactly
# match the redirect URI registered with the Google OAuth client — mismatches
# fail the exchange with invalid_grant. Both are env-var driven (see config.py),
# defaulting to today's local-dev values.
_FRONTEND_URL = FRONTEND_URL
_REDIRECT_URI = OAUTH_REDIRECT_URI


def _build_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_REDIRECT_URI],
        }
    }
    # Disable PKCE: this is a confidential client (we hold a client_secret) and the
    # flow is stateless — /auth/login and /auth/callback build separate Flow objects,
    # so a per-request code_verifier cannot be carried between them. Without this,
    # google-auth-oauthlib auto-generates a code_verifier at login that is lost by
    # callback, causing "invalid_grant: Missing code verifier".
    flow = Flow.from_client_config(
        client_config,
        scopes=_SCOPES,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = _REDIRECT_URI
    return flow


@router.get("/login")
async def login():
    """Return Google OAuth2 authorization URL."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth not configured")
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"auth_url": auth_url}


class LoginPasswordRequest(BaseModel):
    email: str
    password: str


@router.post("/login-password")
async def login_password(req: LoginPasswordRequest, request: Request):
    """Email+password login (login-change plan, 2026-07-23) -- stays under
    /auth/ (public, like /login and /callback), deliberately not behind
    AuthMiddleware since no token exists yet.

    Generic 401 on any failure (unknown email OR wrong password) -- an
    identical message either way, so the response carries no
    user-enumeration signal.
    """
    client_ip = request.client.host if request.client else "unknown"
    email = req.email.strip().lower()

    if login_rate_limiter.is_blocked(client_ip, email):
        raise HTTPException(429, "Too many failed attempts. Try again later.")

    row = fetchone(
        "select user_id, email, name, picture, password_hash, password_changed "
        "from users where email = %s",
        (email,),
    )
    if not row or not row.get("password_hash") or not verify_password(req.password, row["password_hash"]):
        login_rate_limiter.record_failure(client_ip, email)
        raise HTTPException(401, "Invalid email or password")

    login_rate_limiter.record_success(client_ip, email)
    user_id = row["user_id"]
    token = create_token(user_id, row["email"])
    user_json = {
        "id": user_id, "email": row["email"], "name": row.get("name", ""),
        "picture": row.get("picture", ""), "is_admin": is_admin(row["email"]),
        "password_changed": row["password_changed"],
    }
    return {"token": token, "user": user_json}


@router.get("/callback")
async def callback(code: str, request: Request):
    """Exchange OAuth code for tokens, upsert user, issue JWT."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth not configured")

    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        print(f"OAuth token exchange failed: {exc}", file=sys.stderr)
        raise HTTPException(400, "Token exchange failed")

    creds: Credentials = flow.credentials

    # Fetch user profile via People API / userinfo
    service = build("oauth2", "v2", credentials=creds)
    user_info = service.userinfo().get().execute()

    user_id = user_info["id"]
    email = user_info["email"]
    name = user_info.get("name", "")
    picture = user_info.get("picture", "")

    # Login-change plan (2026-07-23): generate+hash a password up front
    # (cheap even when discarded on a re-login) and detect a TRUE first
    # insert via `xmax = 0` so Google re-logins never touch password_hash/
    # password_changed -- only the very first insert for this user_id sets them.
    generated_password = generate_password()
    password_hash = hash_password(generated_password)

    # Upsert user profile
    row = fetchone(
        """
        insert into users (user_id, email, name, picture, password_hash, password_changed)
        values (%s, %s, %s, %s, %s, false)
        on conflict (user_id) do update
          set email = excluded.email, name = excluded.name, picture = excluded.picture
        returning (xmax = 0) as inserted, password_changed
        """,
        (user_id, email, name, picture, password_hash),
    )
    is_new_user, password_changed = row["inserted"], row["password_changed"]

    # Store encrypted Drive tokens
    expires_at = None
    if creds.expiry:
        expires_at = creds.expiry.isoformat()

    execute(
        """
        insert into user_drive_tokens (user_id, access_token_enc, refresh_token_enc, expires_at)
        values (%s, %s, %s, %s)
        on conflict (user_id) do update
          set access_token_enc = excluded.access_token_enc,
              refresh_token_enc = excluded.refresh_token_enc,
              expires_at = excluded.expires_at
        """,
        (user_id, encrypt(creds.token), encrypt(creds.refresh_token or ""), expires_at),
    )

    # Drop any cached DriveStorage built from now-stale tokens so the next request
    # rebuilds from these fresh ones.
    from app.core.drive_factory import evict_user
    evict_user(user_id)

    # Issue session JWT
    token = create_token(user_id, email)

    # PAWN 2.0 Phase B.1: carried on the callback redirect payload (not just
    # /auth/me) since the frontend persists THIS shape to localStorage as its
    # long-lived AuthUser and never re-fetches /auth/me after login.
    user_json = json.dumps({
        "id": user_id, "email": email, "name": name, "picture": picture,
        "is_admin": is_admin(email), "password_changed": password_changed,
    })

    # Redirect frontend to handle token storage
    from urllib.parse import quote
    redirect_url = f"{_FRONTEND_URL}/?token={token}&user={quote(user_json)}"
    if is_new_user:
        # One-time plaintext reveal -- the frontend's GeneratedPasswordModal
        # shows this once then strips it via the existing unconditional
        # history.replaceState({}, '', '/') call, same mechanism already
        # used to remove `token`/`user` from the URL after the callback.
        redirect_url += f"&generated_password={quote(generated_password)}"
    return RedirectResponse(redirect_url)


@router.get("/me")
async def me(request: Request):
    """Return current user profile from JWT."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    token = auth_header[7:]
    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        raise HTTPException(401, "Invalid token")

    # Login-change plan (2026-07-23): explicit column list, not `select *` --
    # `password_hash` must never be returned to the client, regardless of
    # future column additions to `users`.
    row = fetchone(
        "select user_id, email, name, picture, password_changed, created_at "
        "from users where user_id = %s",
        (payload["sub"],),
    )
    if not row:
        raise HTTPException(404, "User not found")
    # PAWN 2.0 Phase B.1: frontend keys off this backend flag rather than
    # duplicating the magic admin email client-side (core.admin.is_admin).
    row["is_admin"] = is_admin(row.get("email"))
    return row


@router.get("/drive/status")
async def drive_status(request: Request):
    """Report whether the current user's Google Drive is linked AND usable.

    Not merely "a token row exists": a user can complete Google login but decline
    the drive.file scope via granular consent, leaving a stored token that Drive
    calls reject. So after confirming a DriveStorage can be built, we make one
    cheap, idempotent Drive call (get_or_create_root) to prove the scope actually
    works — otherwise the Settings page would show "Connected" for someone who
    still gets 412s everywhere.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    token = auth_header[7:]
    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        raise HTTPException(401, "Invalid token")

    from app.core.drive_factory import get_drive_for_user

    drive = await run_in_threadpool(get_drive_for_user, payload["sub"])
    if drive is None:
        return {"connected": False}
    try:
        await run_in_threadpool(drive.get_or_create_root)
    except Exception as exc:
        print(f"Drive status check failed for {payload['sub']}: {exc}", file=sys.stderr)
        return {"connected": False}
    return {"connected": True}


@router.post("/logout")
async def logout():
    """Stateless logout — client drops the JWT."""
    return {"ok": True}
