"""
app/services/auth_service.py
-----------------------------
Password hashing (bcrypt) and JWT token creation/verification.
"""

import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from passlib.context import CryptContext
from jose import JWTError, jwt

load_dotenv()

JWT_SECRET    = os.getenv("JWT_SECRET", "insecure_default_change_me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return bcrypt hash of a plain-text password."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    """
    Encode a JWT with the given payload plus an expiry claim.
    `data` should contain at least {"sub": username, "role": role}.
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload["exp"] = expire
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT. Raises JWTError on invalid/expired tokens.
    Returns the decoded payload dict.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
