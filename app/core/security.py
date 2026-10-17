"""Password hashing (bcrypt) and JWT creation/validation."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """bcrypt adds a random salt automatically. The result is safe to store."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:  # malformed hash or over-long input
        return False


# Used to spend the same time on "unknown user" as on "wrong password",
# so response timing does not reveal which usernames exist.
DUMMY_HASH = hash_password("not-a-real-password-1")


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Returns (token, lifetime_in_seconds)."""
    settings = get_settings()
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict | None:
    """Returns the payload, or None if the token is invalid, tampered with, or expired."""
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
