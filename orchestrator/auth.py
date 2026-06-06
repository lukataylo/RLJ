"""Authentication for the PulseGo orchestrator.

email+password login -> JWT (Bearer). Passwords hashed with bcrypt (passlib). Enforcement
is ENV-GATED via AUTH_REQUIRED so existing tests (which POST without a token) keep passing:

    AUTH_REQUIRED off (default)  -> `require_user` is a no-op, returns an anonymous sentinel.
    AUTH_REQUIRED on  (prod)     -> `require_user` demands a valid `Authorization: Bearer <jwt>`.

Env:
    AUTH_REQUIRED   "true"/"1"/"yes"/"on" to enforce on write endpoints (default off).
    JWT_SECRET      signing secret (a dev default is used + warned about if unset).
    ADMIN_EMAIL / ADMIN_PASSWORD   if both set, an admin user is seeded at startup.
"""
from __future__ import annotations
import os
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

from db import User, SessionLocal

# --------------------------------------------------------------------------- config
_DEV_SECRET = "dev-insecure-secret-change-me"
JWT_ALG = "HS256"
JWT_EXP_HOURS = 12

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)


def auth_required() -> bool:
    """Read AUTH_REQUIRED at call time so tests can toggle enforcement per process."""
    return os.getenv("AUTH_REQUIRED", "false").strip().lower() in ("1", "true", "yes", "on")


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        warnings.warn("JWT_SECRET not set; using an insecure dev default. Set JWT_SECRET in production.",
                      stacklevel=2)
        return _DEV_SECRET
    return secret


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:  # noqa: BLE001 - malformed hash should never 500 a login
        return False


# --------------------------------------------------------------------------- JWT
def create_access_token(user: "User") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.email,
        "uid": user.id,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXP_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALG])


# --------------------------------------------------------------------------- users
def create_user(email: str, password: str, role: str = "dispatcher", session=None) -> "User":
    """Create and persist a user. Raises ValueError if the email already exists."""
    own = session is None
    s = session or SessionLocal()
    try:
        if s.scalar(select(User).where(User.email == email)) is not None:
            raise ValueError("user already exists")
        user = User(email=email, password_hash=hash_password(password), role=role)
        s.add(user)
        s.commit()
        s.refresh(user)
        return user
    finally:
        if own:
            s.close()


def authenticate(email: str, password: str) -> Optional["User"]:
    """Return the User on a correct email+password, else None."""
    s = SessionLocal()
    try:
        user = s.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(password, user.password_hash):
            return None
        return user
    finally:
        s.close()


def seed_admin() -> None:
    """If ADMIN_EMAIL and ADMIN_PASSWORD are set and the user is absent, create an admin."""
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return
    s = SessionLocal()
    try:
        if s.scalar(select(User).where(User.email == email)) is None:
            s.add(User(email=email, password_hash=hash_password(password), role="admin"))
            s.commit()
    finally:
        s.close()


# --------------------------------------------------------------------------- current user
class CurrentUser:
    """Lightweight identity passed to handlers via the auth dependencies."""

    def __init__(self, email: Optional[str], role: str, uid: Optional[int] = None,
                 anonymous: bool = False):
        self.email = email
        self.role = role
        self.uid = uid
        self.anonymous = anonymous


# Sentinel returned when enforcement is off — every endpoint stays open.
ANONYMOUS = CurrentUser(email=None, role="anonymous", uid=None, anonymous=True)


def _user_from_credentials(creds: Optional[HTTPAuthorizationCredentials]) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(creds.credentials)
    except Exception:  # noqa: BLE001 - any decode/expiry error is an invalid token
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    return CurrentUser(email=payload.get("sub"), role=payload.get("role", "dispatcher"),
                       uid=payload.get("uid"))


def require_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> CurrentUser:
    """Env-gated guard for WRITE endpoints.

    AUTH_REQUIRED off -> returns the anonymous sentinel (no check; backward compatible).
    AUTH_REQUIRED on  -> validates the Bearer JWT or raises 401.
    """
    if not auth_required():
        return ANONYMOUS
    return _user_from_credentials(creds)


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> CurrentUser:
    """Always-strict guard (used by GET /auth/me): a valid Bearer JWT or 401, regardless
    of AUTH_REQUIRED — '/auth/me' answers 'who am I', so an absent token means 401."""
    return _user_from_credentials(creds)
