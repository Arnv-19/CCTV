from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base

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
