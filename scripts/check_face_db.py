"""
scripts/check_face_db.py
------------------------
Diagnostic: checks InsightFace model weights on disk and the DB
embedding tables / columns.
"""
import os
import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

SEP = "=" * 60

# ── 1. Model weights on disk ──────────────────────────────────────────────────
buffalo_l_path = Path.home() / ".insightface" / "models" / "buffalo_l"
print(SEP)
print("InsightFace model: buffalo_l")
print(f"  Expected path : {buffalo_l_path}")
print(f"  Exists        : {buffalo_l_path.exists()}")
if buffalo_l_path.exists():
    files = sorted(buffalo_l_path.iterdir())
    print(f"  Files ({len(files)}):")
    for f in files:
        size_kb = f.stat().st_size // 1024
        print(f"    {f.name:40s}  {size_kb:>6} KB")
else:
    print("  WARNING: Model NOT downloaded yet.")
    print("     It will be auto-downloaded on the FIRST enroll request.")

# ── 2. Library versions ───────────────────────────────────────────────────────
print()
print(SEP)
print("Library checks:")
try:
    import insightface
    print(f"  insightface    : {insightface.__version__}  OK")
except ImportError as e:
    print(f"  insightface    : MISSING -- {e}")

try:
    import albumentations as A
    print(f"  albumentations : {A.__version__}  OK")
except ImportError as e:
    print(f"  albumentations : MISSING -- {e}")

try:
    import onnxruntime as ort
    providers = ort.get_available_providers()
    gpu = "CUDAExecutionProvider" in providers
    print(f"  onnxruntime    : {ort.__version__}  OK  (GPU={'YES' if gpu else 'NO - CPU only'})")
    print(f"  providers      : {providers}")
except ImportError as e:
    print(f"  onnxruntime    : MISSING -- {e}")

# ── 3. DB schema check ────────────────────────────────────────────────────────
print()
print(SEP)
print("Database schema check:")
try:
    from sqlalchemy import text
    from app.db.database import SessionLocal, ensure_database_connected

    engine = ensure_database_connected()
    with engine.connect() as conn:

        # employees columns
        result = conn.execute(text(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'employees' "
            "ORDER BY ordinal_position"
        ))
        rows = result.fetchall()
        print()
        print("  employees table:")
        key_cols = {"embedding", "embedding_aug", "is_enrolled", "enrolled_at", "photo_path"}
        for col, dtype in rows:
            marker = "OK" if col in key_cols else "  "
            print(f"    [{marker}] {col:30s} {dtype}")

        # face_embeddings table
        result2 = conn.execute(text(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'face_embeddings' "
            "ORDER BY ordinal_position"
        ))
        rows2 = result2.fetchall()
        print()
        print("  face_embeddings table:")
        if rows2:
            for col, dtype in rows2:
                print(f"    [OK] {col:30s} {dtype}")
        else:
            print("    TABLE DOES NOT EXIST YET")

        # alerts face columns
        result3 = conn.execute(text(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'alerts' "
            "AND column_name LIKE 'face_%' "
            "ORDER BY ordinal_position"
        ))
        rows3 = result3.fetchall()
        print()
        print("  alerts face columns:")
        if rows3:
            for col, dtype in rows3:
                print(f"    [OK] {col:30s} {dtype}")
        else:
            print("    NO face_* columns found -- migration may not have run")

        # Row counts
        r4 = conn.execute(text(
            "SELECT COUNT(*), "
            "COUNT(CASE WHEN is_enrolled = true THEN 1 END) "
            "FROM employees"
        ))
        total, enrolled = r4.fetchone()
        print()
        print(f"  Employee rows : {total} total, {enrolled} enrolled")

        # Sample enrolled embeddings
        if enrolled > 0:
            r5 = conn.execute(text(
                "SELECT id, name, employee_id, "
                "json_array_length(embedding::json) as emb_len, "
                "CASE WHEN embedding_aug IS NOT NULL THEN json_array_length(embedding_aug::json) ELSE 0 END as aug_count "
                "FROM employees WHERE is_enrolled = true LIMIT 5"
            ))
            emps = r5.fetchall()
            print()
            print("  Enrolled employees (sample):")
            for row in emps:
                print(f"    id={row[0]}  name={row[1]:20s}  emp_id={row[2]:10s}  emb_dims={row[3]}  aug_count={row[4]}")

        # Test embedding roundtrip write (rolled back)
        print()
        print("  Embedding write test (rolled back - safe):")
        try:
            conn2 = engine.begin()
            with engine.begin() as txn:
                txn.execute(text(
                    "INSERT INTO employees (name, employee_id, is_enrolled) "
                    "VALUES ('__test__', '__test_diag__', false)"
                ))
                emp_id_row = txn.execute(text(
                    "SELECT id FROM employees WHERE employee_id = '__test_diag__'"
                )).fetchone()
                emp_pk = emp_id_row[0]
                txn.execute(text(
                    "INSERT INTO face_embeddings (employee_id, embedding, model_name) "
                    "VALUES (:eid, :emb::json, 'buffalo_l')"
                ), {"eid": emp_pk, "emb": "[0.1, 0.2, 0.3]"})
                # Rollback by raising
                raise Exception("ROLLBACK_INTENDED")
        except Exception as e:
            if "ROLLBACK_INTENDED" in str(e):
                print("    INSERT + FK roundtrip: PASS (rolled back cleanly)")
            else:
                print(f"    WRITE ERROR: {e}")

except Exception as exc:
    print(f"  DB ERROR: {exc}")

print()
print(SEP)
print("Done.")
