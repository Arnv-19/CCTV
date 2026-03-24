"""
app/db/models.py
----------------
SQLAlchemy ORM models for all database tables.

Tables:
  users               — application users with roles (admin | operator)
  buzzers             — physical alarm devices (USB / HTTP / MQTT / GPIO)
  camera_buzzers      — many-to-many: which buzzers fire for each camera
  camera_models       — per-camera AI model enable/disable flags
  alerts              — violation event log with snapshot, ack status
  burglar_alarm_events — dedicated log for zone-entry burglar alarm triggers
"""


import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, Float,
    DateTime, ForeignKey, Text, UniqueConstraint, JSON,
)
from sqlalchemy.orm import relationship
from app.db.database import Base


class BurglarAlarmConfig(Base):
    """
    Per-camera burglar alarm configuration.

    The alarm fires when:
      1. alarm_enabled is True
      2. Current local time is within [alarm_start_time, alarm_end_time]
      3. A "Person" class is detected inside the monitored zone
         (or any active ROI if monitored_zone_id is NULL)

    Time strings are stored as "HH:MM" (24-hour).
    Overnight windows (e.g. "20:00" → "05:00") are supported.
    """
    __tablename__ = "burglar_alarm_configs"

    id                  = Column(Integer, primary_key=True, index=True)
    camera_id           = Column(Integer, unique=True, nullable=False, index=True)
    alarm_enabled       = Column(Boolean, default=True, nullable=False)
    alarm_start_time    = Column(String(5), nullable=False, default="20:00")  # "HH:MM"
    alarm_end_time      = Column(String(5), nullable=False, default="06:00")  # "HH:MM"
    # If set, only trigger when person is inside this specific ROI zone (UUID).
    # NULL means "any active ROI" (or all detections if no ROIs configured).
    monitored_zone_id   = Column(String(36), nullable=True)
    cooldown_sec        = Column(Integer, default=30, nullable=False)
    created_at          = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at          = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(64), unique=True, nullable=False, index=True)
    email         = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role          = Column(String(16), nullable=False, default="operator")
    # role values: "admin" | "operator"
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login    = Column(DateTime, nullable=True)
    is_active     = Column(Boolean, default=True, nullable=False)

    # Alerts acknowledged by this user
    acknowledged_alerts = relationship(
        "Alert", back_populates="acknowledger", foreign_keys="Alert.acknowledged_by"
    )


class Buzzer(Base):
    __tablename__ = "buzzers"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(128), nullable=False)
    device_id  = Column(String(128), nullable=True)   # e.g. /dev/ttyACM0 for serial
    ip_address = Column(String(64),  nullable=True)   # for HTTP / MQTT transport
    port       = Column(Integer,     nullable=True)   # HTTP port or MQTT port
    gpio_pin   = Column(Integer,     nullable=True)   # for GPIO-based buzzers
    protocol   = Column(String(16),  nullable=False, default="usb")
    # protocol values: "usb" | "http" | "mqtt" | "gpio"
    is_active  = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    camera_assignments = relationship("CameraBuzzer", back_populates="buzzer")


class CameraBuzzer(Base):
    """Junction table linking cameras (by config index) to buzzers."""
    __tablename__ = "camera_buzzers"

    id          = Column(Integer, primary_key=True, index=True)
    # camera_id is the index position in config.yaml camera_feeds list
    camera_id   = Column(Integer, nullable=False, index=True)
    buzzer_id   = Column(Integer, ForeignKey("buzzers.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("camera_id", "buzzer_id", name="uq_camera_buzzer"),
    )

    buzzer = relationship("Buzzer", back_populates="camera_assignments")


class CameraModel(Base):
    """Per-camera AI model enable/disable flag."""
    __tablename__ = "camera_models"

    id         = Column(Integer, primary_key=True, index=True)
    camera_id  = Column(Integer, nullable=False, index=True)
    model_name = Column(String(128), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("camera_id", "model_name", name="uq_camera_model"),
    )


class Alert(Base):
    """Violation event logged by the camera worker on each detection."""
    __tablename__ = "alerts"

    id               = Column(Integer, primary_key=True, index=True)
    camera_id        = Column(Integer, nullable=False, index=True)
    model_name       = Column(String(128), nullable=False)
    violation_type   = Column(String(128), nullable=False)   # e.g. "no_helmet"
    confidence_score = Column(Float, nullable=False)
    snapshot_path    = Column(Text, nullable=True)           # relative path to saved JPEG
    triggered_at     = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    buzzer_activated = Column(Boolean, default=False, nullable=False)

    # Acknowledgement
    acknowledged     = Column(Boolean, default=False, nullable=False, index=True)
    acknowledged_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at  = Column(DateTime, nullable=True)

    acknowledger = relationship(
        "User", back_populates="acknowledged_alerts", foreign_keys=[acknowledged_by]
    )

class BurglarAlarmEvent(Base):
    """
    Dedicated log table for burglar alarm zone-entry events.

    Written by the AlertWriter thread whenever the burglar alarm fires
    (person detected inside the monitored zone during the active window).

    Fields
    ------
    camera_id           — camera that detected the intruder
    zone_id             — ROI zone UUID that was entered (NULL = whole frame)
    confidence_score    — YOLO detection confidence at trigger time
    snapshot_path       — path to the saved JPEG snapshot
    buzzer_activated    — True if a buzzer was fired
    tracker_initialized — True if KCF tracker was started successfully
    triggered_at        — UTC timestamp of the event

    Person location (pixel coords in the resized 640×480 frame)
    bbox_x1, bbox_y1    — top-left corner of the detected person
    bbox_x2, bbox_y2    — bottom-right corner
    frame_width         — frame width at detection time (pixels)
    frame_height        — frame height at detection time (pixels)

    acknowledged        — True once an operator has reviewed it
    acknowledged_by     — FK to the User who acknowledged (nullable)
    acknowledged_at     — UTC timestamp of acknowledgement (nullable)
    """
    __tablename__ = "burglar_alarm_events"

    id                   = Column(Integer, primary_key=True, index=True)
    camera_id            = Column(Integer, nullable=False, index=True)
    zone_id              = Column(String(36), nullable=True)   # ROI uuid or NULL
    confidence_score     = Column(Float, nullable=False, default=0.0)
    snapshot_path        = Column(Text, nullable=True)
    buzzer_activated     = Column(Boolean, default=False, nullable=False)
    tracker_initialized  = Column(Boolean, default=False, nullable=False)
    triggered_at         = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    # Person bounding box at the moment of detection (pixel coords)
    bbox_x1      = Column(Integer, nullable=True)
    bbox_y1      = Column(Integer, nullable=True)
    bbox_x2      = Column(Integer, nullable=True)
    bbox_y2      = Column(Integer, nullable=True)
    frame_width  = Column(Integer, nullable=True)   # 640 normally
    frame_height = Column(Integer, nullable=True)   # 480 normally

    # Acknowledgement
    acknowledged    = Column(Boolean, default=False, nullable=False, index=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)

    acknowledger = relationship(
        "User", foreign_keys=[acknowledged_by]
    )

class ROI(Base):
    """Polygon zone per camera — detections outside all active ROIs are dropped."""
    __tablename__ = "rois"

    roi_id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id      = Column(String(255), nullable=False, index=True)
    name           = Column(String(100), nullable=False)
    # [{x: 0.1, y: 0.2}, …]  — always normalized [0, 1]
    points_normalized = Column(JSON, nullable=False)
    is_active      = Column(Boolean, default=True, nullable=False, index=True)
    color          = Column(String(7), default="#FF5733")   # hex colour
    priority       = Column(Integer, default=0)             # higher checked first
    camera_width   = Column(Integer, nullable=True)         # resolution at draw time
    camera_height  = Column(Integer, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at     = Column(DateTime, default=datetime.utcnow,
                            onupdate=datetime.utcnow, nullable=False)
    created_by     = Column(String(255), nullable=True)

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
