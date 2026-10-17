import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.security import DUMMY_HASH, create_access_token, hash_password, verify_password
from app.database.database import get_db
from app.models import User
from app.schemas.auth import RegisterRequest, TokenOut, UserOut

logger = logging.getLogger("pgpc.auth")  # never log passwords or tokens
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             summary="Register a normal user account",
             description="Creates a USER account. Admin accounts cannot be created here.")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    taken = db.scalar(select(User).where(or_(User.username == data.username, User.email == data.email)))
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username or email is already registered.")
    user = User(username=data.username, email=data.email,
                password_hash=hash_password(data.password), role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("register ok user_id=%s", user.id)
    return user


@router.post("/login", response_model=TokenOut, summary="Log in",
             description="Send username (or email) and password as form data. Returns a JWT bearer token.")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    ident = form.username.strip().lower()
    user = db.scalar(select(User).where(or_(User.username == ident, User.email == ident)))
    # Always run one bcrypt check, so unknown users and wrong passwords take similar time.
    password_ok = verify_password(form.password, user.password_hash if user else DUMMY_HASH)
    if not user or not password_ok:
        logger.warning("login failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password.",
                            headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        logger.warning("login blocked (inactive) user_id=%s", user.id)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled.")
    token, lifetime = create_access_token(user.id, user.role)
    logger.info("login ok user_id=%s role=%s", user.id, user.role)
    return TokenOut(access_token=token, expires_in=lifetime, role=user.role)


@router.get("/me", response_model=UserOut, summary="Current user",
            description="Returns the account that owns the bearer token.")
def me(user: User = Depends(get_current_user)):
    return user
