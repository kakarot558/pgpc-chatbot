import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    # NOTE: there is intentionally no "role" field. Public registration can only create normal users.

    @field_validator("username")
    @classmethod
    def valid_username(cls, v: str) -> str:
        v = v.strip()
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3-50 characters: letters, numbers, dot, dash or underscore.")
        return v.lower()

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v.encode("utf-8")) > 72:  # bcrypt only uses the first 72 bytes
            raise ValueError("Password must be at most 72 bytes.")
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Password must contain at least one letter and one number.")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
