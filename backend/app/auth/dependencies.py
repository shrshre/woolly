"""Auth middleware: FastAPI dependency that protects routes via the JWT cookie."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the logged-in user from the httpOnly cookie, or raise 401."""
    token = request.cookies.get(get_settings().auth_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Log in again.")

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user
