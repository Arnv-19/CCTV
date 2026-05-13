"""User routes: public auth flow + admin user management."""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import PasswordResetToken, User
from app.dependencies import get_current_user, require_admin
from app.services.auth_service import create_access_token, hash_password, verify_password
from app.schemas.user_schema import (_GENERIC_FORGOT_MSG, ForgotPasswordRequest, GenericMessage, LoginRequest, RegisterRequest, ResetPasswordRequest, UserCreate, UserUpdate, AuthTokenResponse, _user_dict, _norm_email, _norm_phone, _derive_username,PasswordReset)
router = APIRouter()

@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=GenericMessage)
def register_user(body: RegisterRequest, db: Session = Depends(get_db)):
    email = _norm_email(body.email)
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        username=_derive_username(email, db),
        email=email,
        phone_number=_norm_phone(body.phone_number),
        password_hash=hash_password(body.password),
        role="operator",
        is_active=True,
    )
    db.add(user)
    db.commit()
    return {"message": "Registration successful. Please sign in."}


@router.post("/login", response_model=AuthTokenResponse)
def login_user(body: LoginRequest, db: Session = Depends(get_db)):
    email = _norm_email(body.email)
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your account is currently inactive")

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token({"sub": user.username, "role": user.role, "id": user.id, "email": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "refresh_token": None,
        "role": user.role,
        "email": user.email,
        "username": user.username,
    }


@router.post("/forgot-password", response_model=GenericMessage)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = _norm_email(body.email)
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is not None and user.is_active:
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        created_at = datetime.now(timezone.utc)

        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=created_at,
            )
        )
        db.commit()
        # In production this token should be sent via email/SMS provider.
        print(f"[auth] Password reset token for {email}: {raw_token}")

    return {"message": _GENERIC_FORGOT_MSG}


@router.post("/reset-password", response_model=GenericMessage)
def reset_password_with_token(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    reset_row = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .first()
    )
    if reset_row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.get(User, reset_row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.password_hash = hash_password(body.new_password)
    reset_row.used_at = now
    db.commit()
    return {"message": "Password reset successful. Please sign in."}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return _user_dict(current_user)


@router.get("/")
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return [_user_dict(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if body.role not in ("admin", "operator"):
        raise HTTPException(400, "role must be 'admin' or 'operator'")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, f"Username '{body.username}' already exists")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, f"Email '{body.email}' already registered")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    # Prevent admin from deactivating themselves
    if user.id == current.id and body.is_active is False:
        raise HTTPException(400, "Cannot deactivate your own account")

    if body.email     is not None: user.email     = body.email
    if body.role      is not None:
        if body.role not in ("admin", "operator"):
            raise HTTPException(400, "role must be 'admin' or 'operator'")
        user.role = body.role
    if body.is_active is not None: user.is_active = body.is_active

    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == current.id:
        raise HTTPException(400, "Cannot deactivate your own account")
    user.is_active = False
    db.commit()
    return {"message": f"User '{user.username}' deactivated"}


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    body: PasswordReset,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": "Password updated"}
