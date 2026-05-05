

from click import DateTime
from sqlalchemy import Column, DateTime, Integer, String, Boolean, ForeignKey
from polars import datetime
from sqlalchemy.orm import relationship

from app.db.database import Base


class BurglarAlarmConfig(Base):
    """
    Configuration for burglar alarm settings on a per-camera basis.
    """
    __tablename__ = "burglar_alarm_configs"

    id                = Column(Integer, primary_key=True, index=True)
    camera_id         = Column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"),unique=True, nullable=False, index=True)
    alarm_enabled     = Column(Boolean, default=True, nullable=False)
    alarm_start_time  = Column(String(5), nullable=False, default="20:00")
    alarm_end_time    = Column(String(5), nullable=False, default="06:00")
    monitored_zone_id = Column(String(36), nullable=True)
    cooldown_sec      = Column(Integer, default=30, nullable=False)
    created_at        = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    camera = relationship("Camera", back_populates="burglar_alarm_config")