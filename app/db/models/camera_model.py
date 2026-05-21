
import uuid
from datetime import datetime

from PIL.ExifTags import Base


from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.database import Base



class CameraModel(Base):
    """
    Legacy per-camera AI model enable/disable flag (keyed by model_name string).

    Kept for backward compatibility with existing API routes and camera_manager
    logic that references model names like "helmet_detection", "gloves_detection".
    Will be superseded by CameraModelAssignment + CameraClassConfig once routes
    are migrated to the new schema.
    """
    __tablename__ = "camera_models"

    id         = Column(Integer, primary_key=True, index=True)
    camera_id  = Column(Integer, nullable=False, index=True)
    model_name = Column(String(128), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("camera_id", "model_name", name="uq_camera_model"),
    )