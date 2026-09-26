import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.security import MIN_PASSWORD_LENGTH
from app.modules.users.models import Language, Role

Username = Annotated[
    str, StringConstraints(to_lower=True, strip_whitespace=True, pattern=r"^[a-z0-9._-]{3,64}$")
]
Password = Annotated[str, StringConstraints(min_length=MIN_PASSWORD_LENGTH, max_length=128)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    full_name: str
    role: Role
    language: Language
    branch_id: uuid.UUID | None
    is_active: bool
    sip_extension: str | None = None
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    username: Username
    full_name: str = Field(min_length=2, max_length=255)
    role: Role
    language: Language = Language.UZ
    branch_id: uuid.UUID | None = None
    password: Password


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: Role | None = None
    language: Language | None = None
    branch_id: uuid.UUID | None = None
    is_active: bool | None = None
    sip_extension: str | None = Field(default=None, pattern=r"^\d{3,4}$")


class PasswordSet(BaseModel):
    password: Password


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class MeUpdate(BaseModel):
    language: Language


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password
