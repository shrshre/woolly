"""SQLAlchemy models."""

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SavedPattern(Base):
    """Join table: a user's saved (bookmarked) patterns."""

    __tablename__ = "saved_patterns"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pattern_id: Mapped[int] = mapped_column(
        ForeignKey("patterns.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProjectStatus(str, enum.Enum):
    queue = "queue"
    active = "active"
    hibernating = "hibernating"
    finished = "finished"


class Project(Base):
    """A user's work-in-progress: a pattern plus materials, notes, and progress."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    pattern_id: Mapped[int] = mapped_column(
        ForeignKey("patterns.id", ondelete="CASCADE"), nullable=False
    )
    yarn: Mapped[str | None] = mapped_column(Text)
    needle_size: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stitch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), default=ProjectStatus.queue, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SeedRun(Base):
    """One execution of the pattern seeding pipeline (manual or scheduled)."""

    __tablename__ = "seed_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    patterns_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    patterns_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="running", nullable=False)  # running / completed / failed


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ravelry_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    designer: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(Text)
    craft: Mapped[str | None] = mapped_column(Text)  # 'knitting' or 'crochet'
    category: Mapped[str | None] = mapped_column(Text)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    ravelry_url: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)  # linked from Ravelry, never hosted
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
