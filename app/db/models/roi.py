from datetime import datetime
import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, JSON
import uuid
from sqlalchemy.orm import relationship
from app.db.database import Base


class ROI(Base):
    """Polygon detection zone for a camera. Detections outside active ROIs are dropped."""
    __tablename__ = "rois"

    roi_id            = Column(String(36), primary_key=True,
                               default=lambda: str(uuid.uuid4()))
    camera_id         = Column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name              = Column(String(100), nullable=False)
    points_normalized = Column(JSON, nullable=False)
    # [{x: 0.1, y: 0.2}, …] — coordinates always normalized to [0, 1]
    is_active         = Column(Boolean, default=True, nullable=False, index=True)
    color             = Column(String(7), default="#FF5733")
    priority          = Column(Integer, default=0)
    # higher priority ROIs are evaluated first
    camera_width      = Column(Integer, nullable=True)
    camera_height     = Column(Integer, nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at        = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by        = Column(String(255), nullable=True)

    camera = relationship("Camera", back_populates="rois")

    def to_dict(self) -> dict:
        return {
            "roi_id":            self.roi_id,
            "camera_id":         self.camera_id,
            "name":              self.name,
            "points_normalized": self.points_normalized,
            "is_active":         self.is_active,
            "color":             self.color,
            "priority":          self.priority,
            "camera_width":      self.camera_width,
            "camera_height":     self.camera_height,
            "created_at":        self.created_at.isoformat() if self.created_at else None,
            "updated_at":        self.updated_at.isoformat() if self.updated_at else None,
            "created_by":        self.created_by,
        }
