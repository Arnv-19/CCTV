"""
app/api/routes/users.py
------------------------
Admin-only user management endpoints.

GET    /api/users/          List all users
POST   /api/users/          Create a new user
PATCH  /api/users/{id}      Update username, email, role, or active status
DELETE /api/users/{id}      Deactivate (soft-delete) a user
POST   /api/users/{id}/reset-password  Set a new password for a user
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.services.auth_service import hash_password
from app.dependencies import require_admin

router = APIRouter()


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


def _user_dict(u: User) -> dict:
    return {
        "id":         u.id,
        "username":   u.username,
        "email":      u.email,
        "role":       u.role,
        "is_active":  u.is_active,
        "created_at": u.created_at,
        "last_login": u.last_login,
    }


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
