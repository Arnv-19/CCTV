from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime
from sqlalchemy.orm import relationship
from app.db.database import Base

class Camera(Base):
    """
    Registry for video sources (RTSP/Webcam) allowing API-based management 
    without server restarts.
    """
    __tablename__ = "cameras"

    # Core Identifiers and Configuration
    id               = Column(Integer, primary_key=True, index=True)
    name             = Column(String(128), nullable=False)
    stream_url       = Column(Text, nullable=False)               # RTSP URL or device index
    location         = Column(String(255), nullable=True)         # Physical installation site[cite: 3]
    is_active        = Column(Boolean, default=True, nullable=False)
    
    # Ingestion and Processing Metadata[cite: 3, 4]
    ingestion_fps    = Column(Integer, default=4, nullable=False)
    detection_width  = Column(Integer, default=960, nullable=False)
    detection_height = Column(Integer, default=720, nullable=False)

    # Face recognition configuration (per-camera) — §4.3
    # face_detection_mode values: "standard" | "long_range"
    face_detection_enabled = Column(Boolean, default=False, nullable=False)
    face_detection_mode    = Column(String(16), default="standard", nullable=False)

    # Audit Timestamps[cite: 3]
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Operational Relationships (Cascading Deletes)[cite: 3, 4]
    rois                 = relationship("ROI", back_populates="camera", cascade="all, delete-orphan")
    model_assignments    = relationship("CameraModelAssignment", back_populates="camera", cascade="all, delete-orphan")
    buzzer_assignments   = relationship("CameraBuzzer", back_populates="camera", cascade="all, delete-orphan")
    burglar_alarm_config = relationship("BurglarAlarmConfig", back_populates="camera", cascade="all, delete-orphan", uselist=False)

    # Historical Event Logs (Preserved on Camera Deletion)[cite: 3, 4]
    alerts                   = relationship("Alert", back_populates="camera")
    burglar_alarm_events     = relationship("BurglarAlarmEvent", back_populates="camera")
    vehicle_detection_events = relationship("VehicleDetectionEvent", back_populates="camera")