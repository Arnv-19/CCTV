from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base


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
    classes           = relationship("ModelClass", back_populates="model", cascade="all, delete-orphan")[cite: 3, 4]
    camera_assignments = relationship("CameraModelAssignment", back_populates="model", cascade="all, delete-orphan")[cite: 3, 4]


