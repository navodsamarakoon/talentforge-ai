import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from talentforge.config import get_settings


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def issue_token(user_id: str, token_version: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "ver": token_version, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expiry_minutes)},
        settings.jwt_secret_value,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict[str, object]:
    return jwt.decode(token, get_settings().jwt_secret_value, algorithms=["HS256"])


def create_invitation_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
