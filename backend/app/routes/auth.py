"""Google OAuth2 authentication routes.

Flow:
  Frontend hits GET /auth/login → receives auth_url → redirects user to Google.
  Google redirects to GET /auth/callback?code=... → backend exchanges code,
  upserts user in Supabase, stores encrypted Drive tokens, issues JWT.
  Backend redirects to frontend /?token=<jwt>&user=<json>.
"""

import json
import os
from datetime import datetime, timezone

# Google may return scopes in a different order, or drop a scope the user did not
# grant via granular consent (e.g. drive.file). oauthlib treats any scope change as
# an error by default; relax that so the token exchange completes. Drive access is
# optional — when drive.file is absent the app falls back to local filesystem storage.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FRONTEND_URL, OAUTH_REDIRECT_URI
from app.core.crypto import encrypt
from app.core.jwt_utils import create_token, decode_token
from app.db.supabase_client import get_db

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


@router.get("/callback")
async def callback(code: str, request: Request):
    """Exchange OAuth code for tokens, upsert user, issue JWT."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth not configured")

    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise HTTPException(400, f"Token exchange failed: {exc}")

    creds: Credentials = flow.credentials

    # Fetch user profile via People API / userinfo
    service = build("oauth2", "v2", credentials=creds)
    user_info = service.userinfo().get().execute()

    user_id = user_info["id"]
    email = user_info["email"]
    name = user_info.get("name", "")
    picture = user_info.get("picture", "")

    db = get_db()

    # Upsert user profile
    db.table("users").upsert(
        {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
        }
    ).execute()

    # Store encrypted Drive tokens
    expires_at = None
    if creds.expiry:
        expires_at = creds.expiry.isoformat()

    db.table("user_drive_tokens").upsert(
        {
            "user_id": user_id,
            "access_token_enc": encrypt(creds.token),
            "refresh_token_enc": encrypt(creds.refresh_token or ""),
            "expires_at": expires_at,
        }
    ).execute()

    # Drop any cached DriveStorage built from now-stale tokens so the next request
    # rebuilds from these fresh ones.
    from app.core.drive_factory import evict_user
    evict_user(user_id)

    # Issue session JWT
    token = create_token(user_id, email)

    user_json = json.dumps({"id": user_id, "email": email, "name": name, "picture": picture})

    # Redirect frontend to handle token storage
    from urllib.parse import quote
    redirect_url = f"{_FRONTEND_URL}/?token={token}&user={quote(user_json)}"
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

    db = get_db()
    result = db.table("users").select("*").eq("user_id", payload["sub"]).single().execute()
    if not result.data:
        raise HTTPException(404, "User not found")
    return result.data


@router.post("/logout")
async def logout():
    """Stateless logout — client drops the JWT."""
    return {"ok": True}
