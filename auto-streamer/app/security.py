"""
Handles security-related functions like authentication, password hashing, and sessions.

This module provides:
- Password hashing and verification using bcrypt.
- Secure, signed session management using Itsdangerous.
- FastAPI dependency for requiring authenticated users on protected routes.
"""
import logging
from typing import Optional

import bcrypt
from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyCookie
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature

from .config import app_config

logger = logging.getLogger(__name__)

# --- Configuration ---
# A strong, secret key is vital for session security.
# It should be set via an environment variable in production.
import os
SECRET_KEY = os.getenv("SECRET_KEY", "a-very-secret-key-for-development")
ADMIN_PASS_HASH = os.getenv("ADMIN_PASS_HASH")
SESSION_COOKIE_NAME = "auth_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days

# --- Serializer for Session Data ---
# URLSafeTimedSerializer adds a timestamp and signature to the session data.
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="cookie-salt")

# --- Cookie Security Scheme ---
cookie_scheme = APIKeyCookie(name=SESSION_COOKIE_NAME, auto_error=False)


# --- Password Hashing ---

def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except ValueError:
        # Occurs if the hash is malformed
        logger.warning("Attempted to verify password with a malformed hash.")
        return False

# --- Session Management ---

def create_session_cookie(username: str = "admin") -> str:
    """Creates a signed and timestamped session cookie value."""
    return serializer.dumps({"username": username})

def get_session_data(request: Request) -> Optional[dict]:
    """
    Retrieves and validates the session data from the request cookie.

    Returns the session data dictionary if valid, otherwise None.
    """
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        return None

    try:
        data = serializer.loads(session_cookie, max_age=SESSION_MAX_AGE_SECONDS)
        return data
    except SignatureExpired:
        logger.info("Session cookie has expired.")
        return None
    except BadTimeSignature:
        logger.warning("Invalid session cookie signature.")
        return None

# --- FastAPI Dependency for Authentication ---

def get_current_user(request: Request) -> Optional[str]:
    """
    FastAPI dependency to get the current authenticated user.
    If the user is not authenticated, it returns None.
    This can be used for optional authentication.
    """
    session_data = get_session_data(request)
    if session_data:
        return session_data.get("username")
    return None

def require_authentication(request: Request):
    """
    FastAPI dependency that requires a user to be authenticated.
    If not, it raises an HTTPException, which can be caught to redirect to login.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# --- CSRF Protection (Simple Implementation) ---
# A more robust solution might use a library like `fastapi-csrf-protect`.

def generate_csrf_token(request: Request) -> str:
    """
    Generates a CSRF token and stores it in the session.
    This is a simple implementation; the token is the session cookie itself.
    For stateless tokens, a double-submit cookie pattern would be better.
    """
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        # This should not happen in a protected route
        return ""
    # We can hash the session cookie to create a derived token
    return bcrypt.hashpw(session_cookie.encode(), bcrypt.gensalt(rounds=4)).decode()


def validate_csrf(request: Request, token: str):
    """Validates a submitted CSRF token against the session."""
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie or not token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing")

    try:
        if not bcrypt.checkpw(session_cookie.encode(), token.encode()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Malformed CSRF token")

    return True
