from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import bcrypt
import jwt
from pydantic import BaseModel

from backend.config import Settings


class DashboardRole(str, Enum):
    ORG_ADMIN = "org_admin"
    SALES_USER = "sales_user"


class TokenPayload(BaseModel):
    sub: str
    role: DashboardRole
    organization_ref: str
    organization_id: str
    user_ref: str | None = None
    user_id: str | None = None
    exp: int


class StatsScope(BaseModel):
    role: DashboardRole | None = None
    organization_ref: str | None = None
    user_ref: str | None = None
    organization_id: str | None = None
    user_id: str | None = None
    is_superadmin: bool = False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(settings: Settings, claims: dict[str, Any], hours: int = 12) -> str:
    secret = settings.jwt_secret
    if not secret:
        raise ValueError("JWT_SECRET non configuré")
    payload = {
        **claims,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> TokenPayload:
    secret = settings.jwt_secret
    if not secret:
        raise ValueError("JWT_SECRET non configuré")
    raw = jwt.decode(token, secret, algorithms=["HS256"])
    return TokenPayload.model_validate(raw)
