"""
app/db/models/employee.py
-------------------------
Employee record for face-recognition enrollment.

Columns
-------
id              — surrogate PK
name            — display name (e.g. "John Smith")
department      — optional organisational unit
employee_id     — HR badge / payroll number (unique)
photo_path      — path to the stored enrolled photo on disk
is_enrolled     — True once a valid face embedding has been stored
embedding       — primary 512-dim InsightFace embedding (JSON list[float])
embedding_aug   — augmented embeddings from the data-augmentation pipeline
                  (JSON list[list[float]] — 8 variants per enroll)
enrolled_at     — timestamp of last successful enrollment
created_at      — record creation timestamp
updated_at      — last update timestamp
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(128), nullable=False)
    department    = Column(String(128), nullable=True)
    employee_id   = Column(String(64), unique=True, nullable=False, index=True)
    photo_path    = Column(Text, nullable=True)

    is_enrolled   = Column(Boolean, default=False, nullable=False)

    # Primary embedding — 512 floats from InsightFace buffalo_l
    embedding     = Column(JSON, nullable=True)

    # Augmented embeddings — list of 512-float lists (one per augmentation)
    embedding_aug = Column(JSON, nullable=True)

    enrolled_at   = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────────────
    # Normalized embedding rows (§4.2)
    face_embeddings = relationship(
        "FaceEmbedding", back_populates="employee",
        cascade="all, delete-orphan",
    )
    # Alerts where this employee’s face was matched (§4.4)
    alerts = relationship(
        "Alert", back_populates="matched_employee",
        foreign_keys="Alert.face_employee_id",
    )
