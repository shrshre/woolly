"""User-scoped routes: the saved-patterns library."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.patterns import pattern_summary_dict
from app.auth.dependencies import get_current_user
from app.db.models import Pattern, SavedPattern, User
from app.db.session import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/library")
async def get_library(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.query(Pattern)
        .join(SavedPattern, SavedPattern.pattern_id == Pattern.id)
        .filter(SavedPattern.user_id == user.id)
        .order_by(SavedPattern.created_at.desc())
        .all()
    )
    return {"patterns": [pattern_summary_dict(p) for p in rows], "total": len(rows)}
