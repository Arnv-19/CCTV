from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base

class BurglarAlarmEvent(Base):
    """
    Dedicated log for burglar alarm zone-entry events.

    camera_id is SET NULL on camera delete — history is always preserved.
    """
    __tablename__ = "burglar_alarm_events"

    id                  = Column(Integer, primary_key=True, index=True)
    camera_id           = Column(
        Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    zone_id             = Column(String(36), nullable=True)
    confidence_score    = Column(Float, nullable=False, default=0.0)
    snapshot_path       = Column(Text, nullable=True)
    buzzer_activated    = Column(Boolean, default=False, nullable=False)
    tracker_initialized = Column(Boolean, default=False, nullable=False)
    triggered_at        = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    bbox_x1      = Column(Integer, nullable=True)
    bbox_y1      = Column(Integer, nullable=True)
    bbox_x2      = Column(Integer, nullable=True)
    bbox_y2      = Column(Integer, nullable=True)
    frame_width  = Column(Integer, nullable=True)
    frame_height = Column(Integer, nullable=True)

    acknowledged    = Column(Boolean, default=False, nullable=False, index=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────
    camera      = relationship("Camera", back_populates="burglar_alarm_events")
    acknowledger = relationship(
        "User", back_populates="acknowledged_burglar_events",
        foreign_keys=[acknowledged_by],
    )