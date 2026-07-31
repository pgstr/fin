from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import Settings
from .models import User, WebSession

password_hasher = PasswordHasher(type=Type.ID, time_cost=3, memory_cost=65536, parallelism=2)
USERNAME_RE = re.compile(r"^[\w.@+-]{3,80}$", re.UNICODE)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username))


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secure_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="finanzplaner-web")


def create_form_token(settings: Settings, purpose: str) -> str:
    return serializer(settings).dumps({"purpose": purpose})


def verify_form_token(settings: Settings, token: str, purpose: str, max_age: int = 3600) -> bool:
    try:
        data = serializer(settings).loads(token, max_age=max_age)
        return data.get("purpose") == purpose
    except (BadSignature, SignatureExpired):
        return False


def create_web_session(db: Session, settings: Settings, user: User) -> tuple[str, WebSession]:
    raw = secrets.token_urlsafe(48)
    record = WebSession(
        token_hash=digest_token(raw),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(36),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
    )
    db.add(record)
    db.flush()
    signed = serializer(settings).dumps(raw)
    return signed, record


def get_web_session(db: Session, settings: Settings, signed_cookie: str | None) -> WebSession | None:
    if not signed_cookie:
        return None
    try:
        raw = serializer(settings).loads(
            signed_cookie, max_age=settings.session_hours * 3600 + 300
        )
    except (BadSignature, SignatureExpired):
        return None
    record = db.get(WebSession, digest_token(raw))
    now = datetime.now(UTC)
    if not record or record.expires_at.replace(tzinfo=UTC) <= now:
        if record:
            db.delete(record)
            db.commit()
        return None
    if not record.user.active:
        return None
    return record


def delete_web_session(db: Session, settings: Settings, signed_cookie: str | None) -> None:
    if not signed_cookie:
        return
    try:
        raw = serializer(settings).loads(signed_cookie, max_age=settings.session_hours * 3600 + 300)
    except (BadSignature, SignatureExpired):
        return
    db.execute(delete(WebSession).where(WebSession.token_hash == digest_token(raw)))
    db.commit()


def purge_expired_sessions(db: Session) -> None:
    db.execute(delete(WebSession).where(WebSession.expires_at < datetime.now(UTC)))


@dataclass(frozen=True)
class Actor:
    actor_type: str
    actor_id: str
    user_id: str
    locale: str
    is_admin: bool = False
    account_ids: frozenset[str] | None = None
    capabilities: frozenset[str] = frozenset()
    token_id: str | None = None

    @classmethod
    def human(cls, user: User) -> Actor:
        return cls("human", user.id, user.id, user.locale, is_admin=user.is_admin)

