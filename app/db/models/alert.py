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

    id                 = Column(Integer, primary_key=True, index=True)
    camera_id          = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    model_name         = Column(String(128), nullable=False)
    violation_type     = Column(String(128), nullable=False)
    confidence_score   = Column(Float, nullable=False)
    snapshot_path      = Column(Text, nullable=True)
    triggered_at       = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    buzzer_activated   = Column(Boolean, default=False, nullable=False)
    session_tracker_id = Column(String(36), nullable=True, index=True)

    acknowledged     = Column(Boolean, default=False, nullable=False, index=True)
    acknowledged_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at  = Column(DateTime, nullable=True)

    # ── Face recognition fields (§4.4) ────────────────────────────────────
    # Nullable — only populated when a face is detected during this alert.
    # face_status values: "matched" | "unknown" | "not_visible" | "too_small" | "low_quality"
    face_employee_id = Column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    face_name        = Column(String(128), nullable=True)   # employee name at time of alert
    face_confidence  = Column(Float, nullable=True)         # cosine similarity 0.0–1.0
    face_status      = Column(String(32), nullable=True)    # matched/unknown/not_visible/too_small/low_quality

    # ── Relationships ─────────────────────────────────────────────────────
    camera      = relationship("Camera", back_populates="alerts")
    acknowledger = relationship(
        "User", back_populates="acknowledged_alerts",
        foreign_keys=[acknowledged_by],
    )
    # Employee whose face was matched (nullable — only set when face_status="matched")
    matched_employee = relationship(
        "Employee", back_populates="alerts",
        foreign_keys="Alert.face_employee_id",
    )
