from pydantic import BaseModel


import re
from typing import Optional
from app.db.models import User
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session


\
_PHONE_ALLOWED = re.compile(r"^[0-9+()\-\s]+$")
_GENERIC_FORGOT_MSG = "If an account exists for this email, password reset instructions have been sent."


def _norm_email(value: str) -> str:
    return value.strip().lower()


def _norm_phone(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _derive_username(email: str, db: Session) -> str:
    base = email.split("@", 1)[0][:40] or "user"
    candidate = base
    suffix = 1
    while db.query(User).filter(User.username == candidate).first() is not None:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "operator"  # "admin" | "operator"


class UserUpdate(BaseModel):
    email:     Optional[EmailStr] = None
    role:      Optional[str]      = None
    is_active: Optional[bool]     = None


class PasswordReset(BaseModel):
    new_password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: Optional[str] = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        phone = _norm_phone(value)
        if phone is None:
            return None
        if not _PHONE_ALLOWED.match(phone):
            raise ValueError("Phone number contains invalid characters")
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 7:
            raise ValueError("Phone number must include at least 7 digits")
        return phone


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None
    role: str
    email: EmailStr
    username: str


class GenericMessage(BaseModel):
    message: str


def _user_dict(u: User) -> dict:
    return {
        "id":         u.id,
        "username":   u.username,
        "email":      u.email,
        "phone_number": u.phone_number,
        "role":       u.role,
        "is_active":  u.is_active,
        "created_at": u.created_at,
        "last_login": u.last_login,
    }

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
