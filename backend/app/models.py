from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Drawing(Base):
    __tablename__ = "drawings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    file_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    head_rev: Mapped[int] = mapped_column(Integer, default=1)
    ai_status: Mapped[str] = mapped_column(String(16), default="idle")  # idle | running | done | error
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    revisions: Mapped[list["Revision"]] = relationship(back_populates="drawing", cascade="all, delete-orphan",
                                                       order_by="Revision.rev_no")
    ai_runs: Mapped[list["AIRun"]] = relationship(cascade="all, delete-orphan", order_by="AIRun.id")
    reviews: Mapped[list["IssueReview"]] = relationship(cascade="all, delete-orphan")
    messages: Mapped[list["ChatMessage"]] = relationship(cascade="all, delete-orphan", order_by="ChatMessage.id")


class Revision(Base):
    """One immutable snapshot of the drawing document; every edit creates the next one."""
    __tablename__ = "revisions"
    # AUTOINCREMENT: ids of discarded redo revisions are never reused (the rule cache is keyed by id)
    __table_args__ = (UniqueConstraint("drawing_id", "rev_no"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drawing_id: Mapped[int] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    rev_no: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(16))          # import | user | auto-fix | ai | assistant
    summary: Mapped[str] = mapped_column(Text, default="")
    ops: Mapped[list] = mapped_column(JSON, default=list)
    changed: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    drawing: Mapped[Drawing] = relationship(back_populates="revisions")


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drawing_id: Mapped[int] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    rev_no: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(128))
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IssueReview(Base):
    """The checker's decision on a finding, keyed by the finding's stable fingerprint."""
    __tablename__ = "issue_reviews"
    __table_args__ = (UniqueConstraint("drawing_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drawing_id: Mapped[int] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16))  # OPEN | ACCEPTED | REJECTED
    comment: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drawing_id: Mapped[int] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSON, default=list)   # human-readable edit messages
    rev_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
