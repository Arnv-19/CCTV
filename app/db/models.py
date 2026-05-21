"""
app/db/models.py
----------------
SQLAlchemy ORM models.

Tables (13 total):

  Core entities
  ─────────────
  cameras                  — RTSP/webcam sources with per-camera stream config
  users                    — application users (admin | operator)
  buzzers                  — physical alarm devices (USB / HTTP / MQTT / GPIO)

  AI model registry
  ─────────────────
  ai_models                — model weight files (ppe_model, vehicle_model …)
  model_classes            — per-model class definitions with role + alert flag

  Per-camera configuration
  ────────────────────────
  camera_model_assignments — which models run on which camera (many-to-many + payload)
  camera_class_configs     — per-camera per-model per-class active flag
  camera_buzzers           — which buzzers fire for each camera
  rois                     — polygon detection zones per camera
  burglar_alarm_configs    — burglar alarm schedule + monitored zone per camera

  Event logs (historical — camera_id SET NULL on camera delete, never cascade)
  ──────────
  alerts                   — PPE / model violation events
  burglar_alarm_events     — zone-entry burglar alarm triggers

  Auth
  ────
  password_reset_tokens    — one-time password reset tokens (hash + expiry)

Relationship map
────────────────
  cameras 1──* camera_model_assignments *──1 ai_models
                        │ 1                        │ 1
                        │ *                        │ *
               camera_class_configs *──1 model_classes

  cameras 1──* camera_buzzers *──1 buzzers
  cameras 1──* rois
  cameras 1──1 burglar_alarm_configs
  cameras 1──* alerts                (SET NULL on camera delete)
  cameras 1──* burglar_alarm_events  (SET NULL on camera delete)

  users   1──* alerts.acknowledged_by
  users   1──* burglar_alarm_events.acknowledged_by
  users   1──* password_reset_tokens (CASCADE delete)
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


# ─────────────────────────────────────────────────────────────────────────────
# Core entities
# ─────────────────────────────────────────────────────────────────────────────

class Camera(Base):
    """
    A single video source (RTSP stream or local webcam).

    Replaces the config.yaml camera_feeds list so cameras can be managed
    via the API without restarting the server.

    All other tables that previously held a plain camera_id integer now
    reference cameras.id as a proper foreign key.
    """
    __tablename__ = "cameras"

    id               = Column(Integer, primary_key=True, index=True)
    name             = Column(String(128), nullable=False)
    stream_url       = Column(Text, nullable=False)              # rtsp://… or "0" for webcam
    location         = Column(String(255), nullable=True)        # physical description
    is_active        = Column(Boolean, default=True, nullable=False)
    ingestion_fps    = Column(Integer, default=4, nullable=False)
    detection_width  = Column(Integer, default=960, nullable=False)
    detection_height = Column(Integer, default=720, nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at       = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────
    model_assignments   = relationship(
        "CameraModelAssignment", back_populates="camera",
        cascade="all, delete-orphan",
    )
    buzzer_assignments  = relationship(
        "CameraBuzzer", back_populates="camera",
        cascade="all, delete-orphan",
    )
    rois                = relationship(
        "ROI", back_populates="camera",
        cascade="all, delete-orphan",
    )
    burglar_alarm_config = relationship(
        "BurglarAlarmConfig", back_populates="camera",
        cascade="all, delete-orphan",
        uselist=False,                                           # one config per camera
    )
    # Event logs: SET NULL on delete — preserve history even when camera is removed
    alerts              = relationship("Alert", back_populates="camera")
    burglar_alarm_events = relationship("BurglarAlarmEvent", back_populates="camera")


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(64), unique=True, nullable=False, index=True)
    email         = Column(String(255), unique=True, nullable=False)
    phone_number  = Column(String(32), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role          = Column(String(16), nullable=False, default="operator")
    # role values: "admin" | "operator"
    is_active     = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login    = Column(DateTime, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────
    acknowledged_alerts = relationship(
        "Alert", back_populates="acknowledger",
        foreign_keys="Alert.acknowledged_by",
    )
    acknowledged_burglar_events = relationship(
        "BurglarAlarmEvent", back_populates="acknowledger",
        foreign_keys="BurglarAlarmEvent.acknowledged_by",
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user",
        cascade="all, delete-orphan",
    )


class Buzzer(Base):
    __tablename__ = "buzzers"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(128), nullable=False)
    device_id  = Column(String(128), nullable=True)    # e.g. /dev/ttyACM0 for serial/USB
    ip_address = Column(String(64),  nullable=True)    # for HTTP / MQTT transport
    port       = Column(Integer,     nullable=True)
    gpio_pin   = Column(Integer,     nullable=True)
    protocol   = Column(String(16),  nullable=False, default="usb")
    # protocol values: "usb" | "http" | "mqtt" | "gpio"
    is_active  = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    camera_assignments = relationship("CameraBuzzer", back_populates="buzzer")


# ─────────────────────────────────────────────────────────────────────────────
# AI model registry
# ─────────────────────────────────────────────────────────────────────────────

class AIModel(Base):
    """
    Registry of every model weight file.

    Adding a new model type (e.g. vehicle, fire) is an INSERT here plus
    inserts into model_classes — no code or config file change needed.
    """
    __tablename__ = "ai_models"

    id                   = Column(Integer, primary_key=True, index=True)
    name                 = Column(String(128), unique=True, nullable=False)
    # name examples: "ppe_model", "vehicle_model", "fire_model"
    display_name         = Column(String(128), nullable=False)
    weight_path          = Column(String(255), nullable=False)
    # weight_path examples: "weights/best (3).pt", "weights/vehicle.pt"
    model_type           = Column(String(32), nullable=False, default="yolov8")
    # model_type values: "yolov8" | "mediapipe" | "kcf"
    yolo_imgsz           = Column(Integer, default=640, nullable=False)
    confidence_threshold = Column(Float, default=0.25, nullable=False)
    description          = Column(Text, nullable=True)
    is_active            = Column(Boolean, default=True, nullable=False)
    created_at           = Column(DateTime, default=datetime.utcnow, nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────
    classes             = relationship(
        "ModelClass", back_populates="model",
        cascade="all, delete-orphan",
    )
    camera_assignments  = relationship(
        "CameraModelAssignment", back_populates="model",
        cascade="all, delete-orphan",
    )


class ModelClass(Base):
    """
    A single detectable class belonging to one AI model.

    class_role controls how the inference pipeline treats a detection:
      "violation" — triggers alert + buzzer, drawn with red bounding box
      "safe"      — compliance confirmed, drawn with green bounding box
      "neutral"   — informational only (e.g. Person, Safety Cone), no alert

    class_index must match the YOLO output index for that model's weights.
    """
    __tablename__ = "model_classes"

    id            = Column(Integer, primary_key=True, index=True)
    model_id      = Column(
        Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_index   = Column(Integer, nullable=False)
    # class_index must match the YOLO class index in the weight file
    class_name    = Column(String(128), nullable=False)
    # class_name examples: "Hardhat", "NO-Hardhat", "Car", "Bus"
    class_role    = Column(String(16), nullable=False, default="neutral")
    # class_role values: "violation" | "safe" | "neutral"
    display_color = Column(String(7), nullable=False, default="#FFFFFF")
    # display_color: hex code for bounding box, e.g. "#FF0000" for red
    trigger_alert = Column(Boolean, default=False, nullable=False)
    # trigger_alert: True for violations that should fire an alert + buzzer
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("model_id", "class_index", name="uq_model_class_index"),
        UniqueConstraint("model_id", "class_name",  name="uq_model_class_name"),
    )

    # ── Relationships ─────────────────────────────────────────────────────
    model         = relationship("AIModel", back_populates="classes")
    camera_configs = relationship(
        "CameraClassConfig", back_populates="model_class",
        cascade="all, delete-orphan",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-camera configuration
# ─────────────────────────────────────────────────────────────────────────────

class CameraModelAssignment(Base):
    """
    Many-to-many junction between cameras and ai_models with payload.

    One row = one model running on one camera.
    confidence_threshold overrides ai_models.confidence_threshold when set.
    """
    __tablename__ = "camera_model_assignments"

    id                   = Column(Integer, primary_key=True, index=True)
    camera_id            = Column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id             = Column(
        Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_enabled           = Column(Boolean, default=True, nullable=False)
    confidence_threshold = Column(Float, nullable=True)
    # NULL → use ai_models.confidence_threshold; set to override per camera
    assigned_at          = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("camera_id", "model_id", name="uq_camera_model_assignment"),
    )

    # ── Relationships ─────────────────────────────────────────────────────
    camera        = relationship("Camera", back_populates="model_assignments")
    model         = relationship("AIModel", back_populates="camera_assignments")
    class_configs = relationship(
        "CameraClassConfig", back_populates="assignment",
        cascade="all, delete-orphan",
    )


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


class CameraClassConfig(Base):
    """
    Per-camera, per-model, per-class active flag.

    One row answers: "For Camera X running Model Y, is Class Z active?"

    Example:
      Camera 1 + PPE model + Hardhat    → is_active=True
      Camera 1 + PPE model + NO-Hardhat → is_active=False  (silenced for this camera)
      Camera 1 + Vehicle  + Car         → is_active=True
      Camera 1 + Vehicle  + Bus         → is_active=False

    Query to get all active classes for a camera:
      SELECT mc.class_name, mc.class_role, m.name AS model_name
      FROM camera_class_configs ccc
      JOIN camera_model_assignments cma ON cma.id = ccc.assignment_id
      JOIN model_classes mc             ON mc.id  = ccc.class_id
      JOIN ai_models m                  ON m.id   = cma.model_id
      WHERE cma.camera_id = :camera_id
        AND cma.is_enabled = true
        AND ccc.is_active  = true
    """
    __tablename__ = "camera_class_configs"

    id            = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(
        Integer, ForeignKey("camera_model_assignments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    class_id      = Column(
        Integer, ForeignKey("model_classes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    is_active     = Column(Boolean, default=True, nullable=False)
    updated_at    = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("assignment_id", "class_id", name="uq_camera_class_config"),
    )

    # ── Relationships ─────────────────────────────────────────────────────
    assignment  = relationship("CameraModelAssignment", back_populates="class_configs")
    model_class = relationship("ModelClass", back_populates="camera_configs")


class CameraBuzzer(Base):
    """Which buzzers fire when a violation is detected on a camera."""
    __tablename__ = "camera_buzzers"

    id          = Column(Integer, primary_key=True, index=True)
    camera_id   = Column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    buzzer_id   = Column(
        Integer, ForeignKey("buzzers.id", ondelete="CASCADE"), nullable=False
    )
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("camera_id", "buzzer_id", name="uq_camera_buzzer"),
    )

    camera = relationship("Camera", back_populates="buzzer_assignments")
    buzzer = relationship("Buzzer", back_populates="camera_assignments")


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


class BurglarAlarmConfig(Base):
    """
    Per-camera burglar alarm configuration.

    The alarm fires when all three conditions are met:
      1. alarm_enabled is True
      2. Current local time is within [alarm_start_time, alarm_end_time]
      3. A Person class is detected inside monitored_zone_id
         (any active ROI when monitored_zone_id is NULL)

    Time strings use "HH:MM" 24-hour format.
    Overnight windows (e.g. "20:00" → "06:00") are supported.
    """
    __tablename__ = "burglar_alarm_configs"

    id                = Column(Integer, primary_key=True, index=True)
    camera_id         = Column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    alarm_enabled     = Column(Boolean, default=True, nullable=False)
    alarm_start_time  = Column(String(5), nullable=False, default="20:00")
    alarm_end_time    = Column(String(5), nullable=False, default="06:00")
    monitored_zone_id = Column(String(36), nullable=True)
    # FK to rois.roi_id kept as a plain string to avoid cross-table
    # cascade complexity; enforced at application level.
    cooldown_sec      = Column(Integer, default=30, nullable=False)
    created_at        = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at        = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    camera = relationship("Camera", back_populates="burglar_alarm_config")


# ─────────────────────────────────────────────────────────────────────────────
# Event logs
# ─────────────────────────────────────────────────────────────────────────────

class Alert(Base):
    """
    Violation event logged by the inference pipeline on each detection.

    camera_id is SET NULL when a camera is deleted so historical records
    are never lost even after hardware is decommissioned.
    """
    __tablename__ = "alerts"

    id               = Column(Integer, primary_key=True, index=True)
    camera_id        = Column(
        Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_name       = Column(String(128), nullable=False)
    violation_type   = Column(String(128), nullable=False)
    # violation_type matches model_classes.class_name for traceability
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


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

class PasswordResetToken(Base):
    """One-time password reset token stored as a SHA-256 hash."""
    __tablename__ = "password_reset_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at    = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="password_reset_tokens")
