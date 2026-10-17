"""Shared building blocks for request/response schemas."""
from datetime import datetime
from typing import Annotated, Any, Generic, Optional, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, StringConstraints, create_model

T = TypeVar("T")


def _blank_to_none(v: Any) -> Any:
    """Forms often send "" for an empty box. Store that as NULL, not as an empty string."""
    return None if isinstance(v, str) and not v.strip() else v


def req(max_len: int, min_len: int = 1):
    """A required, trimmed text field."""
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_len, max_length=max_len)]


def opt(max_len: int):
    """An optional, trimmed text field ("" becomes None)."""
    return Annotated[Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=max_len)]],
                     BeforeValidator(_blank_to_none)]


OptEmail = Annotated[Optional[EmailStr], BeforeValidator(_blank_to_none)]
OptId = Annotated[Optional[int], Field(ge=1)]
REQUIRED = ...  # marks a field that has no default


def make_create_update(name: str, fields: dict[str, tuple[Any, Any]]):
    """Builds <name>Create and <name>Update from ONE field list, so validation rules are written once.
    fields = {"column": (type, default)}.  Create uses the default (REQUIRED = must be sent).
    Update makes every field optional and only changes the fields that were actually sent."""
    create = create_model(f"{name}Create", **{k: (t, d) for k, (t, d) in fields.items()})
    update = create_model(f"{name}Update", **{k: (Optional[t], None) for k, (t, _) in fields.items()})
    return create, update


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Stamped(ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class IdName(ORMModel):
    id: int
    name: str


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int
