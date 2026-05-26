"""
app/db/models/face_embedding.py
--------------------------------
Normalized face-embedding table.

Each employee can have multiple embedding records — one per model or
per augmentation round.  The primary embedding stored on the ``employees``
table is kept for backward-compatibility with the existing inference code;
this table is the canonical, normalized store for long-term management.

Columns
-------
id            — surrogate PK
employee_id   — FK → employees.id  (CASCADE delete)
embedding     — 512-float vector stored as JSON list[float]
model_name    — model that generated the embedding (e.g. "buffalo_l")
created_at    — generation timestamp
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.db.database import Base


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 512-float InsightFace embedding vector
    embedding   = Column(JSON, nullable=False)
    # Name of the model that produced this embedding, e.g. "buffalo_l"
    model_name  = Column(String(64), nullable=False, default="buffalo_l")
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    employee = relationship("Employee", back_populates="face_embeddings")
