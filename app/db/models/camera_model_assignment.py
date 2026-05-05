from datetime import datetime
from sqlalchemy import Column, Integer, Float, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base

class CameraModelAssignment(Base):
    """
    Junction table for many-to-many relationship between Cameras and AI Models.
    Enables specific models to run on specific cameras with threshold overrides.
    """
    __tablename__ = "camera_model_assignments"

    id                   = Column(Integer, primary_key=True, index=True)
    camera_id            = Column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id             = Column(Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False, index=True)
    is_enabled           = Column(Boolean, default=True, nullable=False)
    confidence_threshold = Column(Float, nullable=True) # NULL defaults to AIModel value[cite: 4]    
    assigned_at          = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("camera_id", "model_id", name="uq_camera_model_assignment"),)

    camera               = relationship("Camera", back_populates="model_assignments")
    model                = relationship("AIModel", back_populates="camera_assignments")
    class_configs        = relationship("CameraClassConfig", back_populates="assignment", cascade="all, delete-orphan")