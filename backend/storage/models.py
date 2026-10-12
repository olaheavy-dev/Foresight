"""SQLAlchemy models. Every row belongs to a workspace (docs/07 §2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    """One person's or one household's financial space (docs/00 §6c)."""

    __tablename__ = "workspace"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # wsp_<ULID>
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(2))  # selects the locale pack: GB, IN
    home_currency: Mapped[str] = mapped_column(String(3))  # ISO 4217
    locale: Mapped[str] = mapped_column(String(10))  # en-GB, en-IN
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
