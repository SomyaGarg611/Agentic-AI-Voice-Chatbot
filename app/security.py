"""Authentication + rate limiting.

Identity model:
  • "Sign in with Google" (when GOOGLE_CLIENT_ID is set) — the browser gets a
    Google ID token, we verify it, and mint our own session JWT.
  • Dev email login (fallback when Google isn't configured) — lets you use the
    multi-user flow locally without any Google setup.

Every request/socket carries our session JWT as a Bearer token; the user's id
(sub) scopes their chats and memory so users only ever see their own data.
"""
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Header, HTTPException

from app.config import settings


# ── Session JWTs (our own) ──────────────────────────────────────────────────

def issue_session_jwt(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["sub"],
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_session_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception:
        return None


# ── Google ID token verification ────────────────────────────────────────────

def verify_google_id_token(id_token_str: str) -> Optional[dict]:
    """Verify a Google ID token and return {sub, email, name, picture}."""
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        info = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), settings.google_client_id
        )
        return {
            "sub": f"google:{info['sub']}",
            "email": info.get("email", ""),
            "name": info.get("name", info.get("email", "")),
            "picture": info.get("picture", ""),
        }
    except Exception:
        return None


# ── FastAPI dependency ──────────────────────────────────────────────────────

def _token_from_header(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Require a valid session JWT; returns the user claims."""
    token = _token_from_header(authorization)
    claims = decode_session_jwt(token) if token else None
    if not claims:
        raise HTTPException(status_code=401, detail="Sign in required")
    return claims


def user_from_token(token: Optional[str]) -> Optional[dict]:
    """For the WebSocket (token in query param)."""
    return decode_session_jwt(token) if token else None


# ── Sliding-window rate limiter (in-memory, per-instance) ───────────────────
_hits: dict = defaultdict(deque)


def allow(key: str, max_hits: int, window_s: float = 60.0) -> bool:
    now = time.monotonic()
    dq = _hits[key]
    while dq and now - dq[0] > window_s:
        dq.popleft()
    if len(dq) >= max_hits:
        return False
    dq.append(now)
    return True
