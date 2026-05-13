"""
app/db/database.py
------------------
SQLAlchemy engine and session factory.

Reads connection credentials from environment variables (via .env).
Provides get_db() as a FastAPI dependency that yields a scoped session
and ensures it is closed after each request.
"""

import os
import threading
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
import urllib.parse

load_dotenv()

# Build the PostgreSQL DSN from individual env vars
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "skycctvai")
DB_USER = os.getenv("DB_USER", "skycctvai_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "changeme")

# Percent-encode password to safely include special characters (eg. @)
DB_PASSWORD_QUOTED = urllib.parse.quote_plus(DB_PASSWORD) if DB_PASSWORD is not None else ""

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD_QUOTED}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

_engine_lock = threading.Lock()


def _create_engine():
    db_engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,      # detect stale connections before use
        pool_size=5,
        max_overflow=10,
        echo=False,
    )
    # Verify connectivity at startup
    with db_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return db_engine


try:
    engine = _create_engine()
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


def ensure_database_connected():
    """
    Lazily reconnect the SQLAlchemy engine if the app started before PostgreSQL
    was available. Long-running camera workers use this before DB writes.
    """
    global engine
    if engine is not None:
        return engine

    with _engine_lock:
        if engine is not None:
            return engine
        engine = _create_engine()
        SessionLocal.configure(bind=engine)
        print(f"[DB] Reconnected to PostgreSQL at {DB_HOST}:{DB_PORT}/{DB_NAME}")
        return engine


def get_db():
    """FastAPI dependency: yield a DB session and close it after the request."""
    try:
        ensure_database_connected()
    except Exception as exc:
        raise RuntimeError(
            "Database is not connected. Check DB_* environment variables and PostgreSQL status."
        ) from exc
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
