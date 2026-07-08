"""Project tracker CRUD. All routes require auth; users only see their own projects."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.patterns import pattern_summary_dict
from app.auth.dependencies import get_current_user
from app.db.models import Pattern, Project, ProjectStatus, User
from app.db.session import get_db

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    pattern_id: int  # Ravelry id, as used everywhere in the API
    yarn: str | None = None
    needle_size: str | None = None
    notes: str | None = None
    status: ProjectStatus = ProjectStatus.queue
    progress_pct: int = Field(0, ge=0, le=100)


class ProjectUpdate(BaseModel):
    yarn: str | None = None
    needle_size: str | None = None
    notes: str | None = None
    status: ProjectStatus | None = None
    progress_pct: int | None = Field(None, ge=0, le=100)
    stitch_count: int | None = Field(None, ge=0)
    row_count: int | None = Field(None, ge=0)


def project_dict(project: Project, pattern: Pattern) -> dict:
    return {
        "id": project.id,
        "yarn": project.yarn,
        "needle_size": project.needle_size,
        "notes": project.notes,
        "progress_pct": project.progress_pct,
        "stitch_count": project.stitch_count,
        "row_count": project.row_count,
        "status": project.status.value,
        "pattern": pattern_summary_dict(pattern),
    }


def _get_owned_project(db: Session, user: User, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    pattern = db.query(Pattern).filter(Pattern.ravelry_id == body.pattern_id).one_or_none()
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")

    project = Project(
        user_id=user.id,
        pattern_id=pattern.id,
        yarn=body.yarn,
        needle_size=body.needle_size,
        notes=body.notes,
        status=body.status,
        progress_pct=body.progress_pct,
    )
    db.add(project)
    db.commit()
    return project_dict(project, pattern)


@router.get("")
async def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.query(Project, Pattern)
        .join(Pattern, Project.pattern_id == Pattern.id)
        .filter(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return {"projects": [project_dict(project, pattern) for project, pattern in rows]}


@router.patch("/{project_id}")
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = _get_owned_project(db, user, project_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    pattern = db.get(Pattern, project.pattern_id)
    return project_dict(project, pattern)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    project = _get_owned_project(db, user, project_id)
    db.delete(project)
    db.commit()
