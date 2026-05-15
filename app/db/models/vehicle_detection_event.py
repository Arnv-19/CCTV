from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from app.db.database import Base


class VehicleDetectionEvent(Base):
    """
    One row per detected vehicle with optional number plate OCR result.

    camera_id is SET NULL on camera delete — historical records are preserved.
    plate_number and plate_confidence are NULL when OCR finds no readable text.
    """
    __tablename__ = "vehicle_detection_events"

    id                  = Column(Integer, primary_key=True, index=True)
    camera_id           = Column(
        Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_class       = Column(String(64), nullable=False)
    confidence_score    = Column(Float, nullable=False, default=0.0)
    plate_number        = Column(String(32), nullable=True)
    plate_confidence    = Column(Float, nullable=True)
    snapshot_path       = Column(Text, nullable=True)
    plate_snapshot_path = Column(Text, nullable=True)
    triggered_at        = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # ── Relationships ─────────────────────────────────────────────────────
    camera = relationship("Camera", back_populates="vehicle_detection_events")
