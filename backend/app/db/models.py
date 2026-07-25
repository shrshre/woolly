"""SQLAlchemy models."""

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, DateTime, Enum, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384
IMAGE_EMBEDDING_DIM = 512  # clip-ViT-B-32


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
    image_embedding = mapped_column(Vector(IMAGE_EMBEDDING_DIM), nullable=True)  # CLIP, for visual search
    search_vector = mapped_column(TSVECTOR, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SearchEvent(Base):
    """One semantic-search request — the raw feed for search analytics.

    Written on both the cache-hit and cache-miss paths so cache_hit_rate is
    measurable. top_result_id is the internal Pattern.id (not ravelry_id) of
    the first result in the full ranked list for the query.
    """

    __tablename__ = "search_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    result_count: Mapped[int | None] = mapped_column(Integer)
    top_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("patterns.id", ondelete="SET NULL")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cache_hit: Mapped[bool] = mapped_column(Boolean, server_default="false")
    search_type: Mapped[str] = mapped_column(Text, server_default="hybrid")  # hybrid / semantic
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResultInteraction(Base):
    """A user action on a specific search result (save or Ravelry click).

    position is 1-indexed and absolute across pages (offset + index + 1) so
    save/click rates can be measured against rank.
    """

    __tablename__ = "result_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("search_events.id", ondelete="CASCADE")
    )
    pattern_id: Mapped[int] = mapped_column(ForeignKey("patterns.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # 'save' / 'ravelry_click'
    rerank_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
