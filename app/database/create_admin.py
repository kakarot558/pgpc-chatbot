"""Create the first administrator:  python -m app.database.create_admin
Reads ADMIN_USERNAME, ADMIN_EMAIL and ADMIN_PASSWORD from .env. Never changes an existing account."""
import sys

from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.database.database import SessionLocal
from app.models import User
from app.schemas.auth import RegisterRequest


def main() -> int:
    s = get_settings()
    if not s.admin_email or not s.admin_password:
        print("Set ADMIN_USERNAME, ADMIN_EMAIL and ADMIN_PASSWORD in .env first.")
        return 1
    try:  # reuse the same username/email/password rules as public registration
        data = RegisterRequest(username=s.admin_username, email=s.admin_email, password=s.admin_password)
    except ValidationError as err:
        print("Invalid admin settings:")
        for e in err.errors():
            print(f" - {e['loc'][-1]}: {e['msg']}")
        return 1
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == data.username)):
            print(f"User '{data.username}' already exists. Nothing changed.")
            return 0
        db.add(User(username=data.username, email=data.email,
                    password_hash=hash_password(data.password), role="admin", is_active=True))
        db.commit()
    print(f"Admin '{data.username}' created. Remove ADMIN_PASSWORD from .env now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
