from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base

class CameraBuzzer(Base):
    __tablename__ = "camera_buzzers"
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)[cite: 3, 4]
    buzzer_id = Column(Integer, ForeignKey("buzzers.id", ondelete="CASCADE"), nullable=False)[cite: 3, 4]
    
    camera = relationship("Camera", back_populates="buzzer_assignments")
    buzzer = relationship("Buzzer", back_populates="camera_assignments")