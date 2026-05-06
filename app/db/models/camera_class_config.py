from datetime import datetime
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base

class CameraClassConfig(Base):
    """
    Per-camera configuration to enable or silence specific AI classes[cite: 3, 4].
    Determines if a specific Class (Z) from Model (Y) should be active on Camera (X).
    """
    __tablename__ = "camera_class_configs"

    # Primary and Foreign Keys
    id            = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("camera_model_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id      = Column(Integer, ForeignKey("model_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Configuration State[cite: 3, 4]
    is_active     = Column(Boolean, default=True, nullable=False) # Toggle class detection per camera[cite: 4]
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Constraints: Ensure a specific class is configured only once per assignment
    __table_args__ = (UniqueConstraint("assignment_id", "class_id", name="uq_camera_class_config"),)

    # Relationships[cite: 3, 4]
    assignment    = relationship("CameraModelAssignment", back_populates="class_configs")
    model_class   = relationship("ModelClass", back_populates="camera_configs")