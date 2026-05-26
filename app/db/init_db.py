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
from app.db.models import Alert, User, VehicleDetectionEvent, Employee, FaceEmbedding  # noqa: F401 — ensures tables are registered
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
        # Backfill all known model-type toggle rows for any camera missing them.
        # This ensures the "AI Models per Camera" UI section always has data,
        # even for cameras created before a model type was added to _KNOWN_MODEL_TYPES.
        for _model_type in (
            'helmet_detection', 'gloves_detection', 'vest_detection',
            'fire_detection',
            # 'glasses_detection',  # not in use
            # 'mask_detection',     # not in use
            'vehicle_detection',
        ):
            conn.execute(text(f"""
                INSERT INTO camera_models (camera_id, model_name, is_enabled)
                SELECT c.id, '{_model_type}', true
                FROM cameras c
                WHERE NOT EXISTS (
                    SELECT 1 FROM camera_models cm
                    WHERE cm.camera_id = c.id AND cm.model_name = '{_model_type}'
                )
            """))
        # Feature config columns migrated from config.yaml to DB
        conn.execute(text("ALTER TABLE app_config ADD COLUMN IF NOT EXISTS missing_person_alert JSONB"))
        conn.execute(text("ALTER TABLE app_config ADD COLUMN IF NOT EXISTS crowd_alert JSONB"))
        conn.execute(text("ALTER TABLE app_config ADD COLUMN IF NOT EXISTS dynamic_fps JSONB"))
        # vehicle_detection_events — created by create_all() on new installs;
        # existing deployments need the FK constraints added explicitly.
        conn.execute(text("""
            DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'vehicle_detection_events') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'vehicle_detection_events_camera_id_fkey'
                ) THEN
                    ALTER TABLE vehicle_detection_events
                    ADD CONSTRAINT vehicle_detection_events_camera_id_fkey
                    FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE SET NULL;
                END IF;
            END IF;
            END $$;
        """))

        # ── Seed vehicle AI model (runs on every startup; INSERT is a no-op if
        #    the row already exists).
        conn.execute(text("""
            INSERT INTO ai_models
                (name, display_name, weight_path, model_type,
                 yolo_imgsz, confidence_threshold, description, is_active, created_at)
            SELECT
                'vehicle_model',
                'Vehicle Detection',
                'weights/Vehicle.pt',
                'yolov8',
                640, 0.25,
                'YOLOv8 vehicle detection — detects cars, trucks, buses, motorcycles and extracts number plates via OCR.',
                true,
                NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM ai_models WHERE name = 'vehicle_model'
            );
        """))

        # ── Assign vehicle model to every camera that doesn't have it yet.
        #    camera_model_assignments controls which models the inference server loads.
        conn.execute(text("""
            INSERT INTO camera_model_assignments
                (camera_id, model_id, is_enabled, assigned_at, updated_at)
            SELECT c.id, m.id, true, NOW(), NOW()
            FROM cameras c
            CROSS JOIN ai_models m
            WHERE m.name = 'vehicle_model'
            AND NOT EXISTS (
                SELECT 1 FROM camera_model_assignments
                WHERE camera_id = c.id AND model_id = m.id
            );
        """))
        # alerts.camera_id must be nullable so historical alerts are preserved when
        # a camera is deleted (ON DELETE SET NULL). Drop NOT NULL if still present.
        conn.execute(text("ALTER TABLE alerts ALTER COLUMN camera_id DROP NOT NULL"))
        # Null out any alerts whose camera_id points to a non-existent camera
        # (e.g. camera_id=0 or stale IDs) so the FK constraint can be added cleanly.
        conn.execute(text(
            "UPDATE alerts SET camera_id = NULL "
            "WHERE camera_id IS NOT NULL "
            "AND camera_id NOT IN (SELECT id FROM cameras)"
        ))
        conn.execute(text(
            "DO $$ BEGIN "
            "IF EXISTS ("
            "  SELECT 1 FROM pg_constraint WHERE conname = 'alerts_camera_id_fkey'"
            ") THEN "
            "  ALTER TABLE alerts DROP CONSTRAINT alerts_camera_id_fkey; "
            "END IF; "
            "END $$;"
        ))
        conn.execute(text(
            "DO $$ BEGIN "
            "IF NOT EXISTS ("
            "  SELECT 1 FROM pg_constraint WHERE conname = 'alerts_camera_id_fkey'"
            ") THEN "
            "  ALTER TABLE alerts ADD CONSTRAINT alerts_camera_id_fkey "
            "  FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE SET NULL; "
            "END IF; "
            "END $$;"
        ))

        # ── Face recognition: per-camera config columns (safe no-ops on new installs)
        conn.execute(text(
            "ALTER TABLE cameras ADD COLUMN IF NOT EXISTS face_enabled BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        conn.execute(text(
            "ALTER TABLE cameras ADD COLUMN IF NOT EXISTS face_mode VARCHAR(16) NOT NULL DEFAULT 'off'"
        ))

        # ── Employees table (created by create_all on new installs;
        #    on existing deployments the columns may already exist — use IF NOT EXISTS)
        conn.execute(text("""
            DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'employees'
            ) THEN
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS embedding      JSON;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS embedding_aug  JSON;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS is_enrolled    BOOLEAN NOT NULL DEFAULT FALSE;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS enrolled_at    TIMESTAMP;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS photo_path     TEXT;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS department     VARCHAR(128);
            END IF;
            END $$;
        """))

        # ── §4.2  face_embeddings table ──────────────────────────────────────
        # create_all() handles new installs; this block adds the FK constraint
        # on existing deployments where the table was created without it.
        conn.execute(text("""
            DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'face_embeddings_employee_id_fkey'
            ) THEN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'face_embeddings'
                ) THEN
                    ALTER TABLE face_embeddings
                    ADD CONSTRAINT face_embeddings_employee_id_fkey
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE;
                END IF;
            END IF;
            END $$;
        """))

        # ── §4.3  cameras — rename face_enabled / face_mode ──────────────────
        # RENAME COLUMN is a no-op if the new name already exists.
        # We guard with a column-existence check to stay idempotent.
        conn.execute(text("""
            DO $$ BEGIN
            -- Rename face_enabled → face_detection_enabled
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'cameras' AND column_name = 'face_enabled'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'cameras' AND column_name = 'face_detection_enabled'
            ) THEN
                ALTER TABLE cameras RENAME COLUMN face_enabled TO face_detection_enabled;
            END IF;
            -- Ensure the column exists (new installs covered by create_all)
            ALTER TABLE cameras ADD COLUMN IF NOT EXISTS
                face_detection_enabled BOOLEAN NOT NULL DEFAULT FALSE;
            END $$;
        """))
        conn.execute(text("""
            DO $$ BEGIN
            -- Rename face_mode → face_detection_mode
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'cameras' AND column_name = 'face_mode'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'cameras' AND column_name = 'face_detection_mode'
            ) THEN
                ALTER TABLE cameras RENAME COLUMN face_mode TO face_detection_mode;
                -- Migrate legacy values to the new vocabulary
                UPDATE cameras SET face_detection_mode = 'standard'
                WHERE face_detection_mode IN ('identify', 'detect');
                UPDATE cameras SET face_detection_mode = 'standard'
                WHERE face_detection_mode = 'off' OR face_detection_mode IS NULL;
            END IF;
            -- Ensure the column exists (new installs covered by create_all)
            ALTER TABLE cameras ADD COLUMN IF NOT EXISTS
                face_detection_mode VARCHAR(16) NOT NULL DEFAULT 'standard';
            END $$;
        """))

        # ── §4.4  alerts — new face recognition columns ───────────────────────
        conn.execute(text(
            "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS "
            "face_employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_alerts_face_employee_id "
            "ON alerts (face_employee_id)"
        ))
        conn.execute(text(
            "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS face_name VARCHAR(128)"
        ))
        conn.execute(text(
            "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS face_confidence FLOAT"
        ))
        conn.execute(text(
            "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS face_status VARCHAR(32)"
        ))
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
