"""
SQLAlchemy ORM model for the ROI module.

Standalone usage
----------------
    from roi_module.models import ROIBase, ROI
    ROIBase.metadata.create_all(engine)

Integration with an existing app Base
--------------------------------------
    # In your app's models.py (or a new file), after your Base is defined:
    from roi_module.models import ROI
    ROI.__table__.tometadata(YourBase.metadata)   # re-parent the table

Or simply use ROIBase.metadata.create_all() alongside your own metadata.create_all().
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ROIBase(DeclarativeBase):
    """Isolated declarative base for the ROI module."""
    pass


class ROI(ROIBase):
    __tablename__ = "rois"

    roi_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    camera_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Polygon stored as [{x: 0.1, y: 0.2}, ...]  — always normalized [0, 1]
    points_normalized: Mapped[Any] = mapped_column(JSON, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    color: Mapped[str] = mapped_column(String(7), default="#FF5733")   # hex
    priority: Mapped[int] = mapped_column(Integer, default=0)           # higher = checked first

    # Camera resolution at the time the ROI was drawn — used for display/denormalization
    camera_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def to_dict(self) -> dict:
        return {
            "roi_id": self.roi_id,
            "camera_id": self.camera_id,
            "name": self.name,
            "points_normalized": self.points_normalized,
            "is_active": self.is_active,
            "color": self.color,
            "priority": self.priority,
            "camera_width": self.camera_width,
            "camera_height": self.camera_height,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
        }

    def __repr__(self) -> str:
        return f"<ROI id={self.roi_id!r} camera={self.camera_id!r} name={self.name!r} active={self.is_active}>"


def init_tables(engine) -> None:
    """Create ROI tables. Call once at application startup."""
    ROIBase.metadata.create_all(bind=engine)
