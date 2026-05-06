from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.database import Base

class Alert(Base):
    """
    Violation event logged by the inference pipeline on each detection.

    camera_id is SET NULL when a camera is deleted so historical records
    are never lost even after hardware is decommissioned.
    """
    __tablename__ = "alerts"

    id               = Column(Integer, primary_key=True, index=True)
    camera_id        = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    model_name       = Column(String(128), nullable=False)
    violation_type   = Column(String(128), nullable=False)
    confidence_score = Column(Float, nullable=False)
    snapshot_path    = Column(Text, nullable=True)
    triggered_at     = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    buzzer_activated = Column(Boolean, default=False, nullable=False)

    acknowledged     = Column(Boolean, default=False, nullable=False, index=True)
    acknowledged_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at  = Column(DateTime, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────
    camera      = relationship("Camera", back_populates="alerts")
    acknowledger = relationship(
        "User", back_populates="acknowledged_alerts",
        foreign_keys=[acknowledged_by],
    )
