"""
Google OAuth 2.0 + HS256 JWT auth for Skill-Bridge.

Flow:
  Browser → GET /auth/google  → Google consent screen
  Google  → GET /auth/callback?code=…&state=…
          → issues JWT → redirects to Streamlit ?token=<jwt>

Protected routes use the `get_current_user` FastAPI dependency which
reads the Authorization: Bearer <jwt> header and returns the decoded payload.
"""

import os
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
STREAMLIT_URL = os.getenv("STREAMLIT_URL", "http://localhost:8501")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
REDIRECT_URI = f"{BACKEND_URL}/auth/callback"

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7

# In-memory CSRF state store (sufficient for local single-user use).
# Maps state_token → True; entries are cleared after first use.
_pending_states: dict[str, bool] = {}

_bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _create_jwt(payload: dict) -> str:
    data = payload.copy()
    data["exp"] = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS)
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> dict:
    """Decode the Bearer JWT and return {uid, email, name, photo_url}.
    Raises HTTP 401 if the token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = _decode_jwt(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    return payload


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> Optional[dict]:
    """Like get_current_user but returns None instead of raising, for routes
    that work both authenticated and unauthenticated."""
    if credentials is None:
        return None
    try:
        return _decode_jwt(credentials.credentials)
    except JWTError:
        return None

# ---------------------------------------------------------------------------
# OAuth route handlers (called from main.py)
# ---------------------------------------------------------------------------

def build_google_auth_redirect() -> RedirectResponse:
    """Build the Google OAuth consent URL and redirect the browser to it."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured.")

    state = secrets.token_urlsafe(32)
    _pending_states[state] = True

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{GOOGLE_AUTH_URL}?{query_string}"
    return RedirectResponse(url=url, status_code=302)


async def handle_google_callback(code: str, state: str) -> RedirectResponse:
    """Exchange the auth code for tokens, fetch user info, issue our JWT,
    then redirect the browser back to Streamlit with ?token=<jwt>."""

    # CSRF check
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    del _pending_states[state]

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if not token_resp.is_success:
        logger.error("Token exchange failed: %s", token_resp.text)
        raise HTTPException(status_code=502, detail="Token exchange with Google failed.")

    access_token = token_resp.json().get("access_token")

    # Fetch user info
    async with httpx.AsyncClient() as client:
        info_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if not info_resp.is_success:
        raise HTTPException(status_code=502, detail="Failed to fetch Google user info.")

    info = info_resp.json()
    uid = info["sub"]  # Google's stable user ID

    # Upsert user document in Firestore (import here to avoid circular deps)
    try:
        from backend.firestore_db import upsert_user
        await upsert_user(uid, {
            "email": info.get("email", ""),
            "name": info.get("name", ""),
            "photo_url": info.get("picture", ""),
        })
    except Exception as exc:
        # Non-fatal — log but don't block the login
        logger.warning("Could not upsert user in Firestore: %s", exc)

    jwt_token = _create_jwt({
        "uid": uid,
        "email": info.get("email", ""),
        "name": info.get("name", ""),
        "photo_url": info.get("picture", ""),
    })

    redirect_url = f"{STREAMLIT_URL}?token={jwt_token}"
    return RedirectResponse(url=redirect_url, status_code=302)
