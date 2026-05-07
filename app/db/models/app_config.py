from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.db.database import Base


class AppConfig(Base):
    """
    Singleton table for global configuration shown on the Configuration page.

    Camera stream rows live in `cameras`, while model paths live in `ai_models`.
    This table stores the remaining global runtime flags so `/api/config/` can
    be served entirely from PostgreSQL.
    """
    __tablename__ = "app_config"

    id = Column(Integer, primary_key=True, default=1)
    confidence_threshold = Column(Float, default=0.25, nullable=False)
    alarm_cooldown_sec = Column(Integer, default=10, nullable=False)
    burglar_test_sound = Column(Boolean, default=False, nullable=False)
    esp_ip = Column(String(255), default="", nullable=False)
    use_wifi = Column(Boolean, default=False, nullable=False)
    alarm_transport = Column(String(32), nullable=True)
    alarm_http_token = Column(String(255), default="", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
