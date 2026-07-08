"""Auth routes: register, login, logout, me. JWT is set in an httpOnly cookie."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt input limit is 72 bytes


class UserOut(BaseModel):
    id: int
    email: str


def _set_auth_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
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
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
