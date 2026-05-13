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

from app.db.database import Base, SessionLocal, ensure_database_connected
from app.db.models import Alert, User
from app.services.auth_service import hash_password


def create_tables():
    try:
        engine = ensure_database_connected()
    except Exception:
        # During development it's useful to allow the app to start even when
        # PostgreSQL is not reachable (e.g. running without DB). The rest of
        # the application will handle DB absence gracefully; avoid exiting
        # the whole process from here.
        print("[init_db] WARNING: No database connection. Skipping table creation.")
        return
    print("[init_db] Creating tables...")
    Base.metadata.create_all(bind=engine)
    # Lightweight migrations for existing deployments.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(32)"))
        conn.execute(text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS session_tracker_id VARCHAR(36)"))
        conn.execute(text("ALTER TABLE password_reset_tokens ADD COLUMN IF NOT EXISTS used_at TIMESTAMP"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_alerts_session_tracker_id ON alerts (session_tracker_id)"))
        # Older ROI module versions created rois.camera_id as VARCHAR. The app
        # now uses cameras.id (INTEGER) as the source of truth, so convert the
        # column and discard orphan/non-numeric legacy ROI rows before adding FK.
        conn.execute(text("DELETE FROM rois WHERE camera_id::text !~ '^[0-9]+$'"))
        conn.execute(text(
            "DELETE FROM rois "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM cameras WHERE cameras.id = rois.camera_id::integer"
            ")"
        ))
        conn.execute(text("ALTER TABLE rois DROP CONSTRAINT IF EXISTS rois_camera_id_fkey"))
        conn.execute(text(
            "ALTER TABLE rois "
            "ALTER COLUMN camera_id TYPE INTEGER USING camera_id::integer"
        ))
        conn.execute(text("ALTER TABLE rois ALTER COLUMN camera_id SET NOT NULL"))
        conn.execute(text(
            "DO $$ BEGIN "
            "IF NOT EXISTS ("
            "  SELECT 1 FROM pg_constraint WHERE conname = 'rois_camera_id_fkey'"
            ") THEN "
            "  ALTER TABLE rois ADD CONSTRAINT rois_camera_id_fkey "
            "  FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE; "
            "END IF; "
            "END $$;"
        ))
        # Feature config columns migrated from config.yaml to DB
        conn.execute(text("ALTER TABLE app_config ADD COLUMN IF NOT EXISTS missing_person_alert JSONB"))
        conn.execute(text("ALTER TABLE app_config ADD COLUMN IF NOT EXISTS crowd_alert JSONB"))
        conn.execute(text("ALTER TABLE app_config ADD COLUMN IF NOT EXISTS dynamic_fps JSONB"))
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
    try:
        ensure_database_connected()
    except Exception:
        print("[init_db] WARNING: No database connection. Skipping admin seed.")
        return
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
    print("[init_db] Initialisation complete.")


if __name__ == "__main__":
    init()
