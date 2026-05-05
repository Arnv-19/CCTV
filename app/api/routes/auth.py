"""
app/api/routes/auth.py
-----------------------
POST /api/auth/login  — exchange credentials for a JWT
GET  /api/auth/me     — return the currently logged-in user's profile
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.services.auth_service import verify_password, create_access_token
from app.dependencies import get_current_user
from app.schemas.user_schema import LoginRequest, TokenResponse
router = APIRouter()




@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT access token."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Update last_login timestamp
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token({"sub": user.username, "role": user.role, "id": user.id})
    return TokenResponse(access_token=token, role=user.role, username=user.username)


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return {
        "id":         current_user.id,
        "username":   current_user.username,
        "email":      current_user.email,
        "role":       current_user.role,
        "created_at": current_user.created_at,
        "last_login": current_user.last_login,
    }
