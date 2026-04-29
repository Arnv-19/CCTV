"""
app/db/init_db.py
-----------------
Database initialisation script.

Run once (or on each deploy) to:
  1. Create all tables defined in models.py
  2. Seed a default admin user from environment variables

Usage:
    python -m app.db.init_db
    # or from project root:
    python app/db/init_db.py
"""

import os
import sys
from pathlib import Path

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text

from app.db.database import engine, Base, SessionLocal
from app.db.models import Alert, User
from app.services.auth_service import hash_password


def create_tables():
    if engine is None:
        # During development it's useful to allow the app to start even when
        # PostgreSQL is not reachable (e.g. running without DB). The rest of
        # the application will handle DB absence gracefully; avoid exiting
        # the whole process from here.
        print("[init_db] WARNING: No database connection. Skipping table creation.")
        return
    print("[init_db] Creating tables...")
    Base.metadata.create_all(bind=engine)
    # Lightweight migration for existing deployments.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(32)"))
    print("[init_db] Tables created.")


def seed_admin(db):
    username = os.getenv("DEFAULT_ADMIN_USER", "admin")
    email    = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@skycctvai.local")
    password = os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin@1234")

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        print(f"[init_db] Admin user '{username}' already exists — skipping seed.")
        return

    admin = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    print(f"[init_db] Default admin created: username='{username}'")
    print("[init_db] Change the password immediately after first login.")


def init():
    create_tables()
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
    print("[init_db] Initialisation complete.")


if __name__ == "__main__":
    init()
