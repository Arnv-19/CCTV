from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base

class User(Base):
    __tablename__ = "users"

    # -- Columns --
    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(64), unique=True, nullable=False, index=True)
    email         = Column(String(255), unique=True, nullable=False)
    phone_number  = Column(String(32), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role          = Column(String(16), nullable=False, default="operator")
    is_active     = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login    = Column(DateTime, nullable=True)

    # -- Relationships --
    acknowledged_alerts          = relationship("Alert", back_populates="acknowledger", foreign_keys="Alert.acknowledged_by")
    acknowledged_burglar_events  = relationship("BurglarAlarmEvent", back_populates="acknowledger", foreign_keys="BurglarAlarmEvent.acknowledged_by")
    password_reset_tokens        = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")