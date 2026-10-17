"""Reusable FastAPI dependencies: who is calling, and are they allowed?"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if not payload or not str(payload.get("sub", "")).isdigit():
        raise unauthorized
    # The role is read from the database, not the token, so changes apply immediately.
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Use on every /api/v1/admin/* route."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required.")
    return user


def get_optional_user(token: str | None = Depends(oauth2_optional), db: Session = Depends(get_db)) -> User | None:
    """For public routes that work without an account (the chatbot). A missing, invalid or expired token simply
    means "anonymous"; it never blocks the request."""
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or not str(payload.get("sub", "")).isdigit():
        return None
    user = db.get(User, int(payload["sub"]))
    return user if user is not None and user.is_active else None
