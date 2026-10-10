"""Auth routes: register, login, logout, me, password reset. JWT is set in an httpOnly cookie."""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.reset_tokens import generate_reset_token, hash_reset_token
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import Settings, get_settings
from app.db.models import PasswordResetToken, User
from app.db.session import get_db
from app.services.email_service import send_password_reset_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_COOLDOWN_SECONDS = 60
RESET_MAX_PER_HOUR = 5


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt input limit is 72 bytes


class UserOut(BaseModel):
    id: int
    email: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)
    password: str = Field(min_length=8, max_length=72)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _set_auth_cookie(response: Response, token: str, settings: Settings) -> None:
    # Cross-origin frontend (e.g. Vercel) + API (e.g. Railway) needs SameSite=None
    # with Secure=True so the browser sends the cookie on credentialed fetches.
    samesite: str = "none" if settings.cookie_secure else "lax"
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        samesite=samesite,
        secure=settings.cookie_secure,
        max_age=settings.jwt_expires_days * 86400,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    credentials: Credentials,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    email = credentials.email.lower()
    if db.query(User).filter(User.email == email).one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(email=email, password_hash=hash_password(credentials.password))
    db.add(user)
    db.commit()

    _set_auth_cookie(response, create_access_token(user.id, user.email), settings)
    logger.info("Registered new user %s", user.id)
    return user


@router.post("/login", response_model=UserOut)
def login(
    credentials: Credentials,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    user = db.query(User).filter(User.email == credentials.email.lower()).one_or_none()
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    _set_auth_cookie(response, create_access_token(user.id, user.email), settings)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response, settings: Settings = Depends(get_settings)) -> None:
    samesite: str = "none" if settings.cookie_secure else "lax"
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        samesite=samesite,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/forgot-password", status_code=204)
def forgot_password(
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Email a reset link if the address has an account.

    Always returns 204 so callers cannot tell whether the email is registered.
    """
    user = db.query(User).filter(User.email == body.email.lower()).with_for_update().one_or_none()
    if user is None:
        return

    now = _utc_now()
    hour_ago = now - timedelta(hours=1)
    recent = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id, PasswordResetToken.created_at >= hour_ago)
        .order_by(PasswordResetToken.created_at.desc())
        .all()
    )
    if len(recent) >= RESET_MAX_PER_HOUR:
        logger.info("Password reset rate-limited for user %s", user.id)
        return
    if recent and (now - _as_naive(recent[0].created_at)).total_seconds() < RESET_COOLDOWN_SECONDS:
        logger.info("Password reset cooldown for user %s", user.id)
        return

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now})

    raw, token_hash = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(minutes=settings.password_reset_expires_minutes),
            created_at=now,
        )
    )
    db.commit()

    reset_url = f"{settings.frontend_url.rstrip('/')}/reset-password?token={quote(raw, safe='')}"
    send_password_reset_email(user.email, reset_url, settings)


@router.post("/reset-password", response_model=UserOut)
def reset_password(
    body: ResetPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token_hash = hash_reset_token(body.token)
    user_id = (
        db.query(PasswordResetToken.user_id)
        .filter(PasswordResetToken.token_hash == token_hash)
        .scalar()
    )
    # Lock the account before touching tokens, matching forgot_password's lock
    # order. This also serializes resets using different tokens for one account.
    user = db.query(User).filter(User.id == user_id).with_for_update().one_or_none()
    now = _utc_now()
    consumed = 0 if user is None else db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).update({"used_at": now}, synchronize_session=False)
    if consumed != 1:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="This reset link is invalid or has expired. Request a new one.",
        )

    user.password_hash = hash_password(body.password)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now})
    db.commit()

    _set_auth_cookie(response, create_access_token(user.id, user.email), settings)
    logger.info("Password reset for user %s", user.id)
    return user
