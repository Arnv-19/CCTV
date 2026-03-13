"""
app/db/database.py
------------------
SQLAlchemy engine and session factory.

Reads connection credentials from environment variables (via .env).
Provides get_db() as a FastAPI dependency that yields a scoped session
and ensures it is closed after each request.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

# Build the PostgreSQL DSN from individual env vars
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "skycctvai")
DB_USER = os.getenv("DB_USER", "skycctvai_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "changeme")

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,      # detect stale connections before use
        pool_size=5,
        max_overflow=10,
        echo=False,
    )
    # Verify connectivity at startup
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"[DB] Connected to PostgreSQL at {DB_HOST}:{DB_PORT}/{DB_NAME}")
except Exception as e:
    print(f"[DB] ERROR: Could not connect to PostgreSQL: {e}")
    print("[DB] Check your .env file and ensure PostgreSQL is running.")
    engine = None  # app continues but DB-dependent routes will fail gracefully

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yield a DB session and close it after the request."""
    if engine is None:
        raise RuntimeError(
            "Database is not connected. Check DB_* environment variables and PostgreSQL status."
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
