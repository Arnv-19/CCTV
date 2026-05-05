from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base

class ModelClass(Base):
    __tablename__ = "model_classes"

    id            = Column(Integer, primary_key=True, index=True)
    model_id      = Column(Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False, index=True)
    class_index   = Column(Integer, nullable=False) # YOLO weight index
    class_name    = Column(String(128), nullable=False) # e.g., "Hardhat"
    class_role    = Column(String(16), nullable=False, default="neutral") # "violation" | "safe" | "neutral"
    display_color = Column(String(7), nullable=False, default="#FFFFFF") # Hex code for BB
    trigger_alert = Column(Boolean, default=False, nullable=False) # Triggers buzzer/event
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("model_id", "class_index", name="uq_model_class_index"),
        UniqueConstraint("model_id", "class_name",  name="uq_model_class_name"),
    )

    # Relationships
    model          = relationship("AIModel", back_populates="classes")
    camera_configs = relationship("CameraClassConfig", back_populates="model_class", cascade="all, delete-orphan")