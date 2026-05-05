"""
Generate docs/schema_relationships.docx
Complete professional database schema document for sharing.
"""

import os
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document()

# ── Page setup ────────────────────────────────────────────────────────────────
for section in doc.sections:
    section.top_margin    = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin   = Cm(2.0)
    section.right_margin  = Cm(2.0)
    section.page_width    = Cm(29.7)   # A4 landscape
    section.page_height   = Cm(21.0)

# ── Colour palette ────────────────────────────────────────────────────────────
C_NAVY      = "1F3864"   # headings
C_BLUE      = "2980B9"   # sub-headings
C_RED       = "C0392B"   # FK / cascade labels
C_GREEN     = "1E8449"   # SET NULL labels
C_ORANGE    = "D35400"   # default values
C_GREY      = "7F8C8D"   # secondary text
C_WHITE     = "FFFFFF"
C_HDR_BG    = "1F3864"   # table header bg
C_ALT_BG    = "EBF3FB"   # alternating row bg
C_LEGACY_BG = "FEF9E7"   # legacy table row


# ═════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _set_bg(cell, hex_color):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)

def _set_border(cell, color="BBBBBB", sz="4"):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcB  = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"),   "single")
        el.set(qn("w:sz"),    sz)
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        tcB.append(el)
    tcPr.append(tcB)

def _run(para, text, bold=False, italic=False, size=9,
         color=None, mono=False):
    run = para.add_run(text)
    run.bold       = bold
    run.italic     = italic
    run.font.size  = Pt(size)
    if mono:
        run.font.name = "Courier New"
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENT-LEVEL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def h1(text):
    p = doc.add_heading("", level=1)
    r = p.add_run(text)
    r.font.color.rgb = RGBColor.from_string(C_NAVY)
    r.font.size      = Pt(16)
    r.bold           = True
    return p

def h2(text):
    p = doc.add_heading("", level=2)
    r = p.add_run(text)
    r.font.color.rgb = RGBColor.from_string(C_BLUE)
    r.font.size      = Pt(13)
    r.bold           = True
    return p

def h3(text):
    p = doc.add_heading("", level=3)
    r = p.add_run(text)
    r.font.color.rgb = RGBColor.from_string(C_NAVY)
    r.font.size      = Pt(11)
    r.bold           = True
    return p

def para(text="", bold=False, italic=False, size=10,
         color=None, mono=False, align=None, indent=0):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    if indent:
        p.paragraph_format.left_indent = Inches(indent)
    _run(p, text, bold=bold, italic=italic, size=size,
         color=color, mono=mono)
    return p

def blank():
    doc.add_paragraph()

def divider(color=C_NAVY):
    p   = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pb  = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"),   "single")
    bot.set(qn("w:sz"),    "8")
    bot.set(qn("w:space"), "1")
    bot.set(qn("w:color"), color)
    pb.append(bot)
    pPr.append(pb)

def code(text, indent=0.3):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(indent)
    r = p.add_run(text)
    r.font.name  = "Courier New"
    r.font.size  = Pt(8)
    r.font.color.rgb = RGBColor.from_string("2C3E50")
    return p

def note(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.2)
    r = p.add_run("ℹ  " + text)
    r.italic         = True
    r.font.size      = Pt(9)
    r.font.color.rgb = RGBColor.from_string(C_GREY)
    return p


# ── Smart table builder ───────────────────────────────────────────────────────

def make_table(headers, rows, col_widths=None,
               hdr_bg=C_HDR_BG, hdr_fg=C_WHITE,
               alt_bg=C_ALT_BG, border="BBBBBB",
               row_colors=None):
    """
    row_colors: optional list of hex strings, one per data row.
                Overrides alt_bg for that row when provided.
    """
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl.style     = "Table Grid"

    # Header
    for ci, h in enumerate(headers):
        cell = tbl.rows[0].cells[ci]
        _set_bg(cell, hdr_bg)
        _set_border(cell, border)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        rr = cell.paragraphs[0].add_run(h)
        rr.bold            = True
        rr.font.size       = Pt(8.5)
        rr.font.color.rgb  = RGBColor.from_string(hdr_fg)

    # Data rows
    for ri, row in enumerate(rows):
        if row_colors and ri < len(row_colors) and row_colors[ri]:
            bg = row_colors[ri]
        else:
            bg = alt_bg if ri % 2 == 0 else "FFFFFF"

        for ci, val in enumerate(row):
            cell = tbl.rows[ri + 1].cells[ci]
            _set_bg(cell, bg)
            _set_border(cell, border)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p   = cell.paragraphs[0]
            txt = str(val)

            # Smart colouring based on content
            if txt.startswith("FK →") or "→ cameras" in txt or "→ ai_models" in txt \
                    or "→ users" in txt or "→ buzzers" in txt \
                    or "→ model_classes" in txt or "→ camera_model" in txt:
                rr = p.add_run(txt)
                rr.font.size      = Pt(8.5)
                rr.font.color.rgb = RGBColor.from_string(C_RED)
                rr.italic         = True
            elif "CASCADE" in txt:
                rr = p.add_run(txt)
                rr.font.size      = Pt(8.5)
                rr.font.color.rgb = RGBColor.from_string(C_RED)
                rr.bold           = True
            elif "SET NULL" in txt:
                rr = p.add_run(txt)
                rr.font.size      = Pt(8.5)
                rr.font.color.rgb = RGBColor.from_string(C_GREEN)
                rr.bold           = True
            elif txt.startswith("default:") or txt.startswith("Default:"):
                rr = p.add_run(txt)
                rr.font.size      = Pt(8.5)
                rr.font.color.rgb = RGBColor.from_string(C_ORANGE)
            elif txt in ("PK", "PK (UUID)", "UNIQUE", "INDEX", "PK + INDEX"):
                rr = p.add_run(txt)
                rr.font.size      = Pt(8.5)
                rr.font.color.rgb = RGBColor.from_string(C_NAVY)
                rr.bold           = True
            else:
                rr = p.add_run(txt)
                rr.font.size = Pt(8.5)

    if col_widths:
        for ri in range(len(tbl.rows)):
            for ci, w in enumerate(col_widths):
                tbl.rows[ri].cells[ci].width = Inches(w)

    blank()
    return tbl


# ═════════════════════════════════════════════════════════════════════════════
# TITLE PAGE
# ═════════════════════════════════════════════════════════════════════════════

blank(); blank()

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_run(p, "SkyAI Factory CCTV", bold=True, size=28, color=C_NAVY)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_run(p, "Database Schema & Relationship Reference", size=16, color=C_BLUE)

blank()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_run(p, "Version 2.0  ·  May 2026", size=11, color=C_GREY)

blank()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_run(p, "Confidential — Internal Use Only", italic=True, size=10, color=C_GREY)

blank(); blank()

# Summary box
tbl = doc.add_table(rows=1, cols=4)
tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
labels = ["Total Tables", "Config Tables", "Event Log Tables", "Auth Tables"]
values = ["14", "10", "2", "1"]
colors = [C_NAVY, "2471A3", "1A5276", "154360"]
for ci, (lbl, val, col) in enumerate(zip(labels, values, colors)):
    cell = tbl.rows[0].cells[ci]
    _set_bg(cell, col)
    _set_border(cell, col)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(p, val + "\n", bold=True, size=22, color=C_WHITE)
    _run(p, lbl, size=9, color=C_WHITE)
for ci in range(4):
    tbl.rows[0].cells[ci].width = Inches(2.0)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — TABLE OF CONTENTS
# ═════════════════════════════════════════════════════════════════════════════

h1("Contents")
toc = [
    ("1.", "Schema Overview & Groups"),
    ("2.", "Relationship Map"),
    ("3.", "Foreign Key Reference"),
    ("4.", "Unique Constraints"),
    ("5.", "Core Entity Tables      —  cameras · users · buzzers"),
    ("6.", "AI Model Registry       —  ai_models · model_classes"),
    ("7.", "Per-Camera Config       —  camera_model_assignments · camera_class_configs"),
    ("8.", "Per-Camera Config       —  camera_models (legacy) · camera_buzzers · rois · burglar_alarm_configs"),
    ("9.", "Event Log Tables        —  alerts · burglar_alarm_events"),
    ("10.", "Auth Table              —  password_reset_tokens"),
    ("11.", "FK Chain Walkthroughs"),
    ("12.", "Cascade Delete Rules"),
    ("13.", "Useful SQL Queries"),
]
for num, title in toc:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.3)
    _run(p, f"{num:<5}", bold=True, size=10, color=C_NAVY)
    _run(p, title, size=10)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — OVERVIEW
# ═════════════════════════════════════════════════════════════════════════════

h1("1.  Schema Overview & Groups")
para(
    "The database is organised into four logical groups. "
    "All configuration tables link back to cameras as the root entity.",
    size=10
)
blank()

make_table(
    headers=["#", "Group", "Tables", "Purpose"],
    rows=[
        ["1", "Core Entities",
         "cameras,  users,  buzzers",
         "Physical things that exist in the real world"],
        ["2", "AI Model Registry",
         "ai_models,  model_classes",
         "Defines what each AI model detects and how each class is handled"],
        ["3", "Per-Camera Configuration",
         "camera_model_assignments,  camera_class_configs,\ncamera_models (legacy),  camera_buzzers,\nrois,  burglar_alarm_configs",
         "Links cameras to models, buzzers, zones and alarm schedules"],
        ["4", "Event Logs",
         "alerts,  burglar_alarm_events",
         "Historical records — camera_id SET NULL on delete, never deleted"],
        ["5", "Auth",
         "password_reset_tokens",
         "One-time password reset tokens (SHA-256 hash + expiry)"],
    ],
    col_widths=[0.3, 1.5, 3.0, 3.7],
)

divider()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — RELATIONSHIP MAP
# ═════════════════════════════════════════════════════════════════════════════

h1("2.  Relationship Map")
para("Read  1──*  as one-to-many  and  *──1  as many-to-one.  (CASCADE) means child rows are deleted when parent is deleted.  (SET NULL) means the FK column is set to NULL — the child row is kept.", size=10)
blank()

code(
    "cameras  (root)\n"
    "  │\n"
    "  ├──* camera_model_assignments (CASCADE)  ──1  ai_models\n"
    "  │           │\n"
    "  │           └──* camera_class_configs (CASCADE)  ──1  model_classes  ──1  ai_models\n"
    "  │\n"
    "  ├──* camera_buzzers (CASCADE)  ──1  buzzers\n"
    "  │\n"
    "  ├──* rois (CASCADE)\n"
    "  │\n"
    "  ├──1 burglar_alarm_configs (CASCADE)     [1:1 — one config per camera]\n"
    "  │\n"
    "  ├──* alerts  (SET NULL — history preserved)\n"
    "  │\n"
    "  └──* burglar_alarm_events  (SET NULL — history preserved)\n"
    "\n"
    "users\n"
    "  ├──* alerts.acknowledged_by  (SET NULL)\n"
    "  ├──* burglar_alarm_events.acknowledged_by  (SET NULL)\n"
    "  └──* password_reset_tokens  (CASCADE)\n"
    "\n"
    "ai_models\n"
    "  ├──* model_classes  (CASCADE)\n"
    "  └──* camera_model_assignments  (CASCADE)\n"
    "\n"
    "buzzers\n"
    "  └──* camera_buzzers  (CASCADE)"
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — FK REFERENCE
# ═════════════════════════════════════════════════════════════════════════════

h1("3.  Foreign Key Reference")
para("Complete list of every foreign key in the schema, the column it lives on, what it points to, and what happens when the referenced row is deleted.", size=10)
blank()

make_table(
    headers=["Table", "FK Column", "References", "On Delete", "Nullable"],
    rows=[
        ["camera_model_assignments", "camera_id",       "cameras.id",                   "CASCADE",  "No"],
        ["camera_model_assignments", "model_id",        "ai_models.id",                 "CASCADE",  "No"],
        ["camera_class_configs",     "assignment_id",   "camera_model_assignments.id",  "CASCADE",  "No"],
        ["camera_class_configs",     "class_id",        "model_classes.id",             "CASCADE",  "No"],
        ["model_classes",            "model_id",        "ai_models.id",                 "CASCADE",  "No"],
        ["camera_buzzers",           "camera_id",       "cameras.id",                   "CASCADE",  "No"],
        ["camera_buzzers",           "buzzer_id",       "buzzers.id",                   "CASCADE",  "No"],
        ["rois",                     "camera_id",       "cameras.id",                   "CASCADE",  "No"],
        ["burglar_alarm_configs",    "camera_id",       "cameras.id",                   "CASCADE",  "No"],
        ["alerts",                   "camera_id",       "cameras.id",                   "SET NULL (record kept)", "Yes"],
        ["alerts",                   "acknowledged_by", "users.id",                     "SET NULL (record kept)", "Yes"],
        ["burglar_alarm_events",     "camera_id",       "cameras.id",                   "SET NULL (record kept)", "Yes"],
        ["burglar_alarm_events",     "acknowledged_by", "users.id",                     "SET NULL (record kept)", "Yes"],
        ["password_reset_tokens",    "user_id",         "users.id",                     "CASCADE",  "No"],
    ],
    col_widths=[2.2, 1.6, 2.2, 2.2, 0.7],
)

divider()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — UNIQUE CONSTRAINTS
# ═════════════════════════════════════════════════════════════════════════════

h1("4.  Unique Constraints")
para("These database-level constraints prevent duplicate or conflicting configuration rows.", size=10)
blank()

make_table(
    headers=["Table", "Constraint Name", "Columns", "What It Prevents"],
    rows=[
        ["camera_model_assignments", "uq_camera_model_assignment", "(camera_id, model_id)",    "Assigning the same model to the same camera twice"],
        ["camera_class_configs",     "uq_camera_class_config",    "(assignment_id, class_id)", "Configuring the same class twice for the same camera+model"],
        ["camera_buzzers",           "uq_camera_buzzer",          "(camera_id, buzzer_id)",    "Assigning the same buzzer to the same camera twice"],
        ["model_classes",            "uq_model_class_index",      "(model_id, class_index)",   "Duplicate YOLO class index within a model"],
        ["model_classes",            "uq_model_class_name",       "(model_id, class_name)",    "Duplicate class name within a model"],
        ["burglar_alarm_configs",    "(implicit UNIQUE)",         "camera_id",                 "More than one burglar alarm config per camera"],
        ["camera_models (legacy)",   "uq_camera_model",           "(camera_id, model_name)",   "Registering the same model name for the same camera twice"],
        ["users",                    "(implicit UNIQUE)",         "username",                  "Duplicate usernames"],
        ["users",                    "(implicit UNIQUE)",         "email",                     "Duplicate email addresses"],
        ["password_reset_tokens",    "(implicit UNIQUE)",         "token_hash",                "Duplicate reset token hashes"],
    ],
    col_widths=[2.2, 2.2, 1.8, 3.3],
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — CORE ENTITY TABLES
# ═════════════════════════════════════════════════════════════════════════════

h1("5.  Core Entity Tables")

# ── cameras ──────────────────────────────────────────────────────────────────
h2("5.1  cameras")
para("Stores every video source — RTSP streams or local webcams. This is the root of almost every other table. Previously cameras were stored only as a list in config.yaml. Moving them to the database means cameras can be added, edited or removed via the API without restarting the server.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",               "Integer",     "No",  "auto-increment", "PK + INDEX",  "Unique camera identifier"],
        ["name",             "String(128)", "No",  "—",              "—",           "Display name e.g. 'Gate 1 Camera'"],
        ["stream_url",       "Text",        "No",  "—",              "—",           "RTSP URL or '0' for webcam"],
        ["location",         "String(255)", "Yes", "NULL",           "—",           "Physical location description"],
        ["is_active",        "Boolean",     "No",  "default: True",  "—",           "Soft disable without deletion"],
        ["ingestion_fps",    "Integer",     "No",  "default: 4",     "—",           "Frames per second to ingest from stream"],
        ["detection_width",  "Integer",     "No",  "default: 960",   "—",           "Frame width sent to inference server (px)"],
        ["detection_height", "Integer",     "No",  "default: 720",   "—",           "Frame height sent to inference server (px)"],
        ["created_at",       "DateTime",    "No",  "utcnow",         "—",           "Row creation timestamp (UTC)"],
        ["updated_at",       "DateTime",    "No",  "utcnow",         "auto-update", "Last modification timestamp (UTC)"],
    ],
    col_widths=[1.5, 1.1, 0.7, 1.1, 1.0, 3.0],
)

note("Relationships out:  → camera_model_assignments (CASCADE)  → camera_buzzers (CASCADE)  → rois (CASCADE)  → burglar_alarm_configs (CASCADE)  → alerts (SET NULL)  → burglar_alarm_events (SET NULL)")
blank()

h3("Example Data — cameras")
make_table(
    headers=["id", "name", "stream_url", "location", "is_active", "ingestion_fps", "detection_width", "detection_height"],
    rows=[
        [1, "Gate 1",    "rtsp://192.168.1.10:554/stream", "Main Entrance",  "True",  4, 960, 720],
        [2, "Parking",   "rtsp://192.168.1.11:554/stream", "Parking Lot B",  "True",  4, 960, 720],
        [3, "Warehouse", "rtsp://192.168.1.12:554/stream", "Warehouse Floor","True",  4, 960, 720],
        [4, "Office",    "0",                              "Reception Desk", "False", 4, 640, 480],
    ],
    col_widths=[0.4, 1.0, 2.5, 1.4, 0.7, 0.9, 1.1, 1.1],
)

divider()

# ── users ─────────────────────────────────────────────────────────────────────
h2("5.2  users")
para("Application login accounts. Two roles exist: admin (full access) and operator (view + acknowledge alerts). Users are never hard deleted — the is_active flag is used instead so that historical acknowledged_by references on alerts are never broken.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",            "Integer",     "No",  "auto-increment", "PK + INDEX",    "Unique user identifier"],
        ["username",      "String(64)",  "No",  "—",              "UNIQUE + INDEX", "Login username"],
        ["email",         "String(255)", "No",  "—",              "UNIQUE",         "Email address"],
        ["phone_number",  "String(32)",  "Yes", "NULL",           "—",              "Optional contact number"],
        ["password_hash", "String(255)", "No",  "—",              "—",              "Bcrypt hashed password — never stored plain"],
        ["role",          "String(16)",  "No",  "default: operator","—",            "Values: 'admin' or 'operator'"],
        ["is_active",     "Boolean",     "No",  "default: True",  "—",              "False = soft deleted, cannot log in"],
        ["created_at",    "DateTime",    "No",  "utcnow",         "—",              "Account creation timestamp"],
        ["last_login",    "DateTime",    "Yes", "NULL",           "—",              "Updated on every successful login"],
    ],
    col_widths=[1.4, 1.1, 0.7, 1.2, 1.2, 3.0],
)

note("Relationships out:  → alerts.acknowledged_by (SET NULL)  → burglar_alarm_events.acknowledged_by (SET NULL)  → password_reset_tokens (CASCADE)")
blank()

h3("Example Data — users")
make_table(
    headers=["id", "username", "email", "role", "is_active", "last_login"],
    rows=[
        [1, "admin",    "admin@skyai.com",    "admin",    "True",  "2026-05-05 09:00"],
        [2, "raj",      "raj@skyai.com",      "operator", "True",  "2026-05-05 08:45"],
        [3, "krishnam", "krishnam@skyai.com", "operator", "True",  "2026-05-04 17:30"],
    ],
    col_widths=[0.4, 1.1, 2.0, 0.9, 0.9, 1.8],
)

divider()

# ── buzzers ───────────────────────────────────────────────────────────────────
h2("5.3  buzzers")
para("Physical alarm devices that sound when a violation is detected. Supports four connection protocols. One buzzer can be shared across multiple cameras via camera_buzzers.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",         "Integer",     "No",  "auto-increment", "PK + INDEX", "Unique buzzer identifier"],
        ["name",       "String(128)", "No",  "—",              "—",          "Display name e.g. 'Gate Buzzer'"],
        ["device_id",  "String(128)", "Yes", "NULL",           "—",          "Serial port for USB protocol e.g. /dev/ttyACM0"],
        ["ip_address", "String(64)",  "Yes", "NULL",           "—",          "IP address for HTTP or MQTT protocol"],
        ["port",       "Integer",     "Yes", "NULL",           "—",          "Port number for HTTP or MQTT protocol"],
        ["gpio_pin",   "Integer",     "Yes", "NULL",           "—",          "GPIO pin number for GPIO protocol"],
        ["protocol",   "String(16)",  "No",  "default: usb",   "—",          "Values: 'usb' | 'http' | 'mqtt' | 'gpio'"],
        ["is_active",  "Boolean",     "No",  "default: True",  "—",          "Enable / disable without deletion"],
        ["created_at", "DateTime",    "No",  "utcnow",         "—",          "Creation timestamp"],
    ],
    col_widths=[1.3, 1.1, 0.7, 1.1, 1.0, 3.5],
)

note("Relationships out:  → camera_buzzers (CASCADE delete when buzzer deleted)")
blank()

h3("Example Data — buzzers")
make_table(
    headers=["id", "name", "protocol", "device_id", "ip_address", "port", "is_active"],
    rows=[
        [1, "Gate Buzzer",   "usb",  "/dev/ttyACM0", "NULL",          "NULL", "True"],
        [2, "Floor Buzzer",  "http", "NULL",          "192.168.1.50", "8080", "True"],
        [3, "Office Buzzer", "mqtt", "NULL",          "192.168.1.51", "1883", "True"],
        [4, "GPIO Buzzer",   "gpio", "NULL",          "NULL",          "NULL", "True"],
    ],
    col_widths=[0.4, 1.4, 0.9, 1.4, 1.4, 0.6, 0.8],
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — AI MODEL REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

h1("6.  AI Model Registry")

# ── ai_models ─────────────────────────────────────────────────────────────────
h2("6.1  ai_models")
para("Registry of every YOLO weight file. Previously model paths were hardcoded in config.yaml. Moving them here means a new model type (e.g. vehicle, fire) can be added as a database INSERT with no code or config file changes required.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",                   "Integer",     "No",  "auto-increment", "PK + INDEX", "Unique model identifier"],
        ["name",                 "String(128)", "No",  "—",              "UNIQUE",     "Internal key e.g. 'ppe_model', 'vehicle_model'"],
        ["display_name",         "String(128)", "No",  "—",              "—",          "Human-readable name e.g. 'PPE Detection'"],
        ["weight_path",          "String(255)", "No",  "—",              "—",          "Relative path to .pt weight file e.g. weights/best (3).pt"],
        ["model_type",           "String(32)",  "No",  "default: yolov8","—",          "Values: 'yolov8' | 'mediapipe' | 'kcf'"],
        ["yolo_imgsz",           "Integer",     "No",  "default: 640",   "—",          "YOLO input resolution — must match training"],
        ["confidence_threshold", "Float",       "No",  "default: 0.25",  "—",          "Model-level default confidence (overridable per camera)"],
        ["description",          "Text",        "Yes", "NULL",           "—",          "Optional notes about the model"],
        ["is_active",            "Boolean",     "No",  "default: True",  "—",          "Inactive models are skipped by the inference server"],
        ["created_at",           "DateTime",    "No",  "utcnow",         "—",          "Creation timestamp"],
    ],
    col_widths=[1.6, 1.1, 0.7, 1.1, 1.0, 3.0],
)

note("Relationships out:  → model_classes (CASCADE)  → camera_model_assignments (CASCADE)")
blank()

h3("Example Data — ai_models")
make_table(
    headers=["id", "name", "display_name", "weight_path", "model_type", "imgsz", "confidence", "is_active"],
    rows=[
        [1, "ppe_model",     "PPE Detection",      "weights/best (3).pt", "yolov8", 640, 0.25, "True"],
        [2, "vehicle_model", "Vehicle Detection",  "weights/vehicle.pt",  "yolov8", 640, 0.40, "True"],
        [3, "fire_model",    "Fire & Smoke",       "weights/fire.pt",     "yolov8", 640, 0.60, "True"],
        [4, "gloves_model",  "Glove Detection",    "weights/best 1.pt",   "yolov8", 640, 0.25, "True"],
        [5, "person_model",  "Person / Burglar",   "weights/person_model.pt","yolov8",640, 0.30,"True"],
    ],
    col_widths=[0.4, 1.3, 1.5, 2.0, 1.0, 0.6, 0.9, 0.8],
)

divider()

# ── model_classes ─────────────────────────────────────────────────────────────
h2("6.2  model_classes")
para("Every class that a model can detect, with its role and display configuration. class_index must match the integer class index that YOLO outputs for that weight file.", size=10)
blank()

p = doc.add_paragraph()
p.paragraph_format.left_indent = Inches(0.2)
_run(p, "class_role values:", bold=True, size=10)
_run(p, "\n  violation  ", bold=True, size=9, color=C_RED)
_run(p, "→  Triggers alert + buzzer, red bounding box", size=9)
_run(p, "\n  safe       ", bold=True, size=9, color=C_GREEN)
_run(p, "→  Compliance confirmed, green bounding box, no alert", size=9)
_run(p, "\n  neutral    ", bold=True, size=9, color=C_GREY)
_run(p, "→  Informational only (e.g. Person, Safety Cone), no alert", size=9)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",            "Integer",     "No",  "auto-increment", "PK + INDEX",   "Unique class identifier"],
        ["model_id",      "Integer",     "No",  "—",              "FK → ai_models.id  CASCADE  INDEX", "Parent model"],
        ["class_index",   "Integer",     "No",  "—",              "UNIQUE with model_id", "YOLO output class index — must match weight file"],
        ["class_name",    "String(128)", "No",  "—",              "UNIQUE with model_id", "Class label e.g. 'Hardhat', 'NO-Hardhat', 'Car'"],
        ["class_role",    "String(16)",  "No",  "default: neutral","—",            "Values: 'violation' | 'safe' | 'neutral'"],
        ["display_color", "String(7)",   "No",  "default: #FFFFFF","—",            "Hex colour for bounding box e.g. '#FF0000'"],
        ["trigger_alert", "Boolean",     "No",  "default: False", "—",             "True = fires alert + buzzer on detection"],
        ["created_at",    "DateTime",    "No",  "utcnow",         "—",             "Creation timestamp"],
    ],
    col_widths=[1.4, 1.1, 0.7, 1.2, 2.0, 3.1],
)

note("Relationships out:  → camera_class_configs (CASCADE delete when this class is deleted)")
blank()

h3("Example Data — model_classes  (PPE model id=1  +  Vehicle model id=2  +  Fire model id=3)")
make_table(
    headers=["id", "model_id", "class_index", "class_name", "class_role", "display_color", "trigger_alert"],
    rows=[
        [1,  "1 (ppe)",     0,  "Fall-Detected", "violation", "#FF0000", "True"],
        [2,  "1 (ppe)",     1,  "Gloves",         "safe",      "#00FF00", "False"],
        [3,  "1 (ppe)",     3,  "Hardhat",         "safe",      "#00FF00", "False"],
        [4,  "1 (ppe)",     4,  "Ladder",          "neutral",   "#FFFFFF", "False"],
        [5,  "1 (ppe)",     5,  "Mask",            "safe",      "#00FF00", "False"],
        [6,  "1 (ppe)",     6,  "NO-Gloves",       "violation", "#FF0000", "True"],
        [7,  "1 (ppe)",     8,  "NO-Hardhat",      "violation", "#FF0000", "True"],
        [8,  "1 (ppe)",    10,  "NO-Safety Vest",  "violation", "#FF0000", "True"],
        [9,  "1 (ppe)",    11,  "Person",          "neutral",   "#0000FF", "False"],
        [10, "1 (ppe)",    13,  "Safety Vest",     "safe",      "#00FF00", "False"],
        [11, "2 (vehicle)", 0,  "Car",             "neutral",   "#FFFF00", "False"],
        [12, "2 (vehicle)", 1,  "Bus",             "neutral",   "#FFFF00", "False"],
        [13, "2 (vehicle)", 2,  "Bike",            "neutral",   "#FFFF00", "False"],
        [14, "2 (vehicle)", 3,  "Unauthorized-Vehicle","violation","#FF0000","True"],
        [15, "3 (fire)",    0,  "Fire",            "violation", "#FF4500", "True"],
        [16, "3 (fire)",    1,  "Smoke",           "violation", "#808080", "True"],
    ],
    col_widths=[0.4, 1.1, 0.9, 1.5, 1.0, 1.2, 1.0],
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — PER-CAMERA CONFIG (assignments + class configs)
# ═════════════════════════════════════════════════════════════════════════════

h1("7.  Per-Camera Configuration  —  Assignments & Class Configs")

# ── camera_model_assignments ──────────────────────────────────────────────────
h2("7.1  camera_model_assignments")
para("Many-to-many junction between cameras and ai_models with payload columns. One row = one model running on one camera. The confidence_threshold column allows overriding the model-level default on a per-camera basis.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",                   "Integer",  "No",  "auto-increment", "PK + INDEX",                            "Unique assignment identifier"],
        ["camera_id",            "Integer",  "No",  "—",              "FK → cameras.id  CASCADE  INDEX",       "Which camera"],
        ["model_id",             "Integer",  "No",  "—",              "FK → ai_models.id  CASCADE  INDEX",     "Which model"],
        ["is_enabled",           "Boolean",  "No",  "default: True",  "—",                                     "Runtime on/off — False pauses without deleting assignment"],
        ["confidence_threshold", "Float",    "Yes", "NULL",           "—",                                     "NULL = use ai_models.confidence_threshold;  set to override"],
        ["assigned_at",          "DateTime", "No",  "utcnow",         "—",                                     "When the model was assigned to this camera"],
        ["updated_at",           "DateTime", "No",  "utcnow",         "auto-update  UNIQUE(camera_id, model_id)","Last change timestamp"],
    ],
    col_widths=[1.7, 1.0, 0.7, 1.1, 2.2, 2.8],
)

note("Relationships out:  → camera_class_configs (CASCADE)")
blank()

h3("Example Data — camera_model_assignments")
make_table(
    headers=["id", "camera_id", "model_id", "is_enabled", "confidence_threshold", "Meaning"],
    rows=[
        [1, "1 (Gate 1)",    "1 (ppe_model)",     "True",  "NULL → uses 0.25", "Gate 1 runs PPE model"],
        [2, "1 (Gate 1)",    "2 (vehicle_model)", "True",  "NULL → uses 0.40", "Gate 1 also runs vehicle model"],
        [3, "2 (Parking)",   "2 (vehicle_model)", "True",  "NULL → uses 0.40", "Parking runs vehicle model only"],
        [4, "3 (Warehouse)", "1 (ppe_model)",     "True",  "NULL → uses 0.25", "Warehouse runs PPE model"],
        [5, "3 (Warehouse)", "3 (fire_model)",    "True",  "0.60",             "Warehouse runs fire model with custom threshold"],
    ],
    col_widths=[0.4, 1.3, 1.7, 0.9, 1.7, 2.5],
)

divider()

# ── camera_class_configs ──────────────────────────────────────────────────────
h2("7.2  camera_class_configs")
para("The most granular control in the schema. One row answers: 'For Camera X running Model Y, is Class Z active?' This allows silencing specific classes for a camera without disabling the whole model.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",            "Integer",  "No",  "auto-increment", "PK + INDEX",                                  "Unique config identifier"],
        ["assignment_id", "Integer",  "No",  "—",              "FK → camera_model_assignments.id  CASCADE  INDEX","Links to the camera+model assignment"],
        ["class_id",      "Integer",  "No",  "—",              "FK → model_classes.id  CASCADE  INDEX  UNIQUE(assignment_id, class_id)","Which class"],
        ["is_active",     "Boolean",  "No",  "default: True",  "—",                                           "False = this class is silenced for this camera+model"],
        ["updated_at",    "DateTime", "No",  "utcnow",         "auto-update",                                 "Last change timestamp"],
    ],
    col_widths=[1.4, 1.0, 0.7, 1.1, 2.8, 2.5],
)

blank()
h3("Example Data — camera_class_configs  (showing Gate 1 + PPE + Vehicle)")
make_table(
    headers=["id", "assignment_id", "class_id (class_name)", "is_active", "Meaning"],
    rows=[
        [1,  "1 (Gate1 + PPE)",     "3  (Hardhat)",          "True",  "Gate 1 checks for helmets"],
        [2,  "1 (Gate1 + PPE)",     "7  (NO-Hardhat)",        "True",  "Gate 1 alerts on no-helmet"],
        [3,  "1 (Gate1 + PPE)",     "2  (Gloves)",            "False", "Gate 1 ignores glove compliance"],
        [4,  "1 (Gate1 + PPE)",     "6  (NO-Gloves)",         "False", "Gate 1 ignores missing gloves"],
        [5,  "1 (Gate1 + PPE)",     "10 (Safety Vest)",       "True",  "Gate 1 checks for safety vest"],
        [6,  "1 (Gate1 + PPE)",     "8  (NO-Safety Vest)",    "True",  "Gate 1 alerts on missing vest"],
        [7,  "2 (Gate1 + Vehicle)", "11 (Car)",               "True",  "Gate 1 tracks cars"],
        [8,  "2 (Gate1 + Vehicle)", "12 (Bus)",               "True",  "Gate 1 tracks buses"],
        [9,  "2 (Gate1 + Vehicle)", "13 (Bike)",              "False", "Gate 1 ignores bikes"],
        [10, "4 (WH + PPE)",        "3  (Hardhat)",           "True",  "Warehouse checks helmets"],
        [11, "5 (WH + Fire)",       "15 (Fire)",              "True",  "Warehouse detects fire"],
        [12, "5 (WH + Fire)",       "16 (Smoke)",             "True",  "Warehouse detects smoke"],
    ],
    col_widths=[0.4, 1.8, 2.0, 0.9, 3.4],
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — REMAINING CONFIG TABLES
# ═════════════════════════════════════════════════════════════════════════════

h1("8.  Per-Camera Configuration  —  Legacy / Buzzers / ROIs / Burglar Alarm")

# ── camera_models (legacy) ────────────────────────────────────────────────────
h2("8.1  camera_models  (Legacy Table)")
para("Original per-camera model flag table keyed by a model_name string such as 'helmet_detection' or 'gloves_detection'. Kept for backward compatibility with existing API routes. Will be superseded by camera_model_assignments + camera_class_configs once routes are migrated.", size=10, color=C_GREY)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",         "Integer",     "No",  "auto-increment", "PK + INDEX",                             "Unique row identifier"],
        ["camera_id",  "Integer",     "No",  "—",              "INDEX  UNIQUE(camera_id, model_name)",   "Config.yaml camera index (no FK)"],
        ["model_name", "String(128)", "No",  "—",              "UNIQUE(camera_id, model_name)",          "e.g. 'helmet_detection', 'gloves_detection'"],
        ["is_enabled", "Boolean",     "No",  "default: True",  "—",                                      "Enable / disable flag"],
        ["updated_at", "DateTime",    "Yes", "utcnow",         "auto-update",                            "Last change timestamp"],
    ],
    col_widths=[1.3, 1.1, 0.7, 1.1, 2.2, 3.1],
    hdr_bg="7D6608", row_colors=[C_LEGACY_BG]*5,
)

note("⚠  camera_id in this table is a plain integer (no FK). Will be migrated to camera_model_assignments.")
blank()

divider()

# ── camera_buzzers ────────────────────────────────────────────────────────────
h2("8.2  camera_buzzers")
para("Junction table linking cameras to buzzers. When a violation fires on a camera, the inference pipeline looks up this table to know which physical buzzers to activate. One camera can trigger multiple buzzers. One buzzer can serve multiple cameras.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",          "Integer",  "No", "auto-increment", "PK + INDEX",                                     "Unique assignment identifier"],
        ["camera_id",   "Integer",  "No", "—",              "FK → cameras.id  CASCADE  INDEX  UNIQUE(camera_id, buzzer_id)", "Which camera"],
        ["buzzer_id",   "Integer",  "No", "—",              "FK → buzzers.id  CASCADE  UNIQUE(camera_id, buzzer_id)",        "Which buzzer"],
        ["assigned_at", "DateTime", "No", "utcnow",         "—",                                              "Assignment timestamp"],
    ],
    col_widths=[1.2, 1.0, 0.7, 1.1, 3.0, 2.5],
)

blank()
h3("Example Data — camera_buzzers")
make_table(
    headers=["id", "camera_id (camera)", "buzzer_id (buzzer)", "Meaning"],
    rows=[
        [1, "1  (Gate 1)",    "1  (Gate Buzzer)",   "Gate 1 violation → Gate Buzzer sounds"],
        [2, "1  (Gate 1)",    "3  (Office Buzzer)", "Gate 1 violation → Office Buzzer also sounds"],
        [3, "2  (Parking)",   "2  (Floor Buzzer)",  "Parking violation → Floor Buzzer sounds"],
        [4, "3  (Warehouse)", "2  (Floor Buzzer)",  "Warehouse violation → same Floor Buzzer sounds"],
    ],
    col_widths=[0.4, 1.8, 1.9, 4.4],
)

divider()

# ── rois ──────────────────────────────────────────────────────────────────────
h2("8.3  rois  (Regions of Interest)")
para("Polygon detection zones drawn on a camera frame. Any detection that falls outside all active ROIs is dropped before alerting — this prevents false alarms in areas of the frame that should not be monitored. Multiple ROIs per camera are supported. Points are always stored as normalised [0–1] coordinates so they remain valid at any resolution.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["roi_id",            "String(36)",  "No",  "UUID v4",        "PK (UUID)",        "Unique zone identifier (auto-generated UUID)"],
        ["camera_id",         "Integer",     "No",  "—",              "FK → cameras.id  CASCADE  INDEX", "Parent camera"],
        ["name",              "String(100)", "No",  "—",              "—",                "Display name e.g. 'Entry Gate Zone'"],
        ["points_normalized", "JSON",        "No",  "—",              "—",                "Polygon vertices [{x:0.1,y:0.2},…] — normalised to [0,1]"],
        ["is_active",         "Boolean",     "No",  "default: True",  "INDEX",            "Only active ROIs are used for filtering"],
        ["color",             "String(7)",   "Yes", "default: #FF5733","—",               "Hex colour used to draw the zone on stream"],
        ["priority",          "Integer",     "Yes", "default: 0",     "—",                "Higher priority zones are evaluated first"],
        ["camera_width",      "Integer",     "Yes", "NULL",           "—",                "Frame width at the time the zone was drawn"],
        ["camera_height",     "Integer",     "Yes", "NULL",           "—",                "Frame height at the time the zone was drawn"],
        ["created_at",        "DateTime",    "No",  "utcnow",         "—",                "Creation timestamp"],
        ["updated_at",        "DateTime",    "No",  "utcnow",         "auto-update",      "Last modification timestamp"],
        ["created_by",        "String(255)", "Yes", "NULL",           "—",                "Username of the user who drew the zone"],
    ],
    col_widths=[1.5, 1.0, 0.7, 1.2, 1.7, 3.4],
)

divider()

# ── burglar_alarm_configs ─────────────────────────────────────────────────────
h2("8.4  burglar_alarm_configs")
para("One row per camera (enforced by UNIQUE on camera_id). Stores the after-hours intruder detection schedule. The alarm fires when: (1) alarm_enabled is True AND (2) current local time is within [alarm_start_time, alarm_end_time] AND (3) a Person class is detected inside monitored_zone_id. Overnight windows such as 20:00 → 06:00 are supported.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",                "Integer",    "No",  "auto-increment", "PK + INDEX",              "Unique config identifier"],
        ["camera_id",         "Integer",    "No",  "—",              "FK → cameras.id  CASCADE  UNIQUE  INDEX", "Parent camera (one config per camera)"],
        ["alarm_enabled",     "Boolean",    "No",  "default: True",  "—",                       "Master on/off switch for this camera's burglar alarm"],
        ["alarm_start_time",  "String(5)",  "No",  "default: 20:00", "—",                       "Alarm active from this time — format HH:MM (24-hour)"],
        ["alarm_end_time",    "String(5)",  "No",  "default: 06:00", "—",                       "Alarm active until this time — supports overnight windows"],
        ["monitored_zone_id", "String(36)", "Yes", "NULL",           "—",                       "ROI uuid to monitor; NULL = any active ROI / whole frame"],
        ["cooldown_sec",      "Integer",    "No",  "default: 30",    "—",                       "Seconds to wait before firing the alarm again"],
        ["created_at",        "DateTime",   "No",  "utcnow",         "—",                       "Creation timestamp"],
        ["updated_at",        "DateTime",   "No",  "utcnow",         "auto-update",             "Last modification timestamp"],
    ],
    col_widths=[1.6, 1.0, 0.7, 1.2, 2.0, 3.0],
)

blank()
h3("Example Data — burglar_alarm_configs")
make_table(
    headers=["id", "camera_id", "alarm_enabled", "start", "end", "monitored_zone_id", "cooldown_sec"],
    rows=[
        [1, "1 (Gate 1)",    "True",  "20:00", "06:00", "uuid-gate-zone",  "30s — fires max every 30s"],
        [2, "2 (Parking)",   "False", "20:00", "06:00", "NULL",            "30s — disabled, won't fire"],
        [3, "3 (Warehouse)", "True",  "18:00", "07:00", "uuid-wh-zone",    "60s — longer cooldown"],
    ],
    col_widths=[0.4, 1.2, 1.1, 0.7, 0.7, 1.7, 2.0],
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — EVENT LOG TABLES
# ═════════════════════════════════════════════════════════════════════════════

h1("9.  Event Log Tables")
para("Event tables use SET NULL (not CASCADE) on camera_id so that historical records are never deleted even when a camera is decommissioned. The camera_id column is nullable to accommodate this.", size=10, color=C_RED)
blank()

# ── alerts ────────────────────────────────────────────────────────────────────
h2("9.1  alerts")
para("Every PPE or model violation detected by the inference pipeline generates one row here. Operators review and acknowledge alerts from the dashboard. violation_type matches model_classes.class_name for full traceability.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",               "Integer",     "No",  "auto-increment", "PK + INDEX",        "Unique alert identifier"],
        ["camera_id",        "Integer",     "Yes", "NULL",           "FK → cameras.id  SET NULL  INDEX", "Which camera triggered the alert — NULL if camera deleted"],
        ["model_name",       "String(128)", "No",  "—",              "—",                 "Model that detected the violation e.g. 'ppe_model'"],
        ["violation_type",   "String(128)", "No",  "—",              "—",                 "Class that fired e.g. 'NO-Hardhat' — matches model_classes.class_name"],
        ["confidence_score", "Float",       "No",  "—",              "—",                 "YOLO detection confidence 0.0 – 1.0"],
        ["snapshot_path",    "Text",        "Yes", "NULL",           "—",                 "Relative path to saved JPEG snapshot"],
        ["triggered_at",     "DateTime",    "No",  "utcnow",         "INDEX",             "UTC timestamp of the detection"],
        ["buzzer_activated", "Boolean",     "No",  "default: False", "—",                 "True if a buzzer was fired for this alert"],
        ["acknowledged",     "Boolean",     "No",  "default: False", "INDEX",             "True once an operator has reviewed this alert"],
        ["acknowledged_by",  "Integer",     "Yes", "NULL",           "FK → users.id  SET NULL", "User who acknowledged — NULL until reviewed"],
        ["acknowledged_at",  "DateTime",    "Yes", "NULL",           "—",                 "UTC timestamp of acknowledgement"],
    ],
    col_widths=[1.5, 1.0, 0.7, 1.1, 1.9, 3.3],
)

blank()
h3("Example Data — alerts")
make_table(
    headers=["id", "camera_id", "model_name", "violation_type", "confidence", "triggered_at", "acknowledged", "acknowledged_by"],
    rows=[
        [1, "1 (Gate 1)",  "ppe_model",  "NO-Hardhat",    "0.87", "2026-05-05 10:32", "False", "NULL"],
        [2, "1 (Gate 1)",  "ppe_model",  "NO-Hardhat",    "0.91", "2026-05-05 10:35", "True",  "2 (raj)"],
        [3, "2 (Parking)", "ppe_model",  "NO-Safety Vest","0.76", "2026-05-05 11:02", "False", "NULL"],
        [4, "3 (Warehouse)","fire_model","Fire",           "0.95", "2026-05-05 11:15", "True",  "1 (admin)"],
        [5, "NULL ← deleted cam","ppe_model","NO-Gloves",  "0.80", "2026-05-04 09:10", "True", "1 (admin)"],
    ],
    col_widths=[0.4, 1.4, 1.1, 1.4, 0.9, 1.7, 1.1, 1.5],
)

divider()

# ── burglar_alarm_events ──────────────────────────────────────────────────────
h2("9.2  burglar_alarm_events")
para("Dedicated log for after-hours intruder detection events. Also stores the bounding box of the detected person so the exact position in the frame can be reviewed. camera_id is SET NULL if the camera is later deleted.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",                  "Integer",  "No",  "auto-increment", "PK + INDEX",        "Unique event identifier"],
        ["camera_id",           "Integer",  "Yes", "NULL",           "FK → cameras.id  SET NULL  INDEX", "Which camera — NULL if camera deleted"],
        ["zone_id",             "String(36)","Yes","NULL",           "—",                 "ROI uuid where person was detected; NULL = whole frame"],
        ["confidence_score",    "Float",    "No",  "default: 0.0",   "—",                 "YOLO person detection confidence 0.0 – 1.0"],
        ["snapshot_path",       "Text",     "Yes", "NULL",           "—",                 "Relative path to saved JPEG snapshot"],
        ["buzzer_activated",    "Boolean",  "No",  "default: False", "—",                 "True if a buzzer was fired"],
        ["tracker_initialized", "Boolean",  "No",  "default: False", "—",                 "True if KCF tracker was started to follow the person"],
        ["triggered_at",        "DateTime", "No",  "utcnow",         "INDEX",             "UTC timestamp of the detection"],
        ["bbox_x1",             "Integer",  "Yes", "NULL",           "—",                 "Bounding box top-left x (pixels in resized frame)"],
        ["bbox_y1",             "Integer",  "Yes", "NULL",           "—",                 "Bounding box top-left y"],
        ["bbox_x2",             "Integer",  "Yes", "NULL",           "—",                 "Bounding box bottom-right x"],
        ["bbox_y2",             "Integer",  "Yes", "NULL",           "—",                 "Bounding box bottom-right y"],
        ["frame_width",         "Integer",  "Yes", "NULL",           "—",                 "Frame width at detection time (pixels)"],
        ["frame_height",        "Integer",  "Yes", "NULL",           "—",                 "Frame height at detection time (pixels)"],
        ["acknowledged",        "Boolean",  "No",  "default: False", "INDEX",             "True once an operator has reviewed this event"],
        ["acknowledged_by",     "Integer",  "Yes", "NULL",           "FK → users.id  SET NULL", "User who acknowledged"],
        ["acknowledged_at",     "DateTime", "Yes", "NULL",           "—",                 "UTC timestamp of acknowledgement"],
    ],
    col_widths=[1.6, 1.0, 0.7, 1.1, 1.8, 3.3],
)

blank()
h3("Example Data — burglar_alarm_events")
make_table(
    headers=["id", "camera_id", "zone_id", "confidence", "bbox_x1/y1", "bbox_x2/y2", "tracker", "acknowledged_by"],
    rows=[
        [1, "1 (Gate 1)",    "uuid-gate-zone", "0.88", "x1=120  y1=80", "x2=200  y2=310", "True",  "NULL"],
        [2, "2 (Parking)",   "NULL",           "0.79", "x1=300  y1=50", "x2=410  y2=280", "False", "2 (raj)"],
        [3, "3 (Warehouse)", "uuid-wh-zone",   "0.92", "x1=200  y1=100","x2=350  y2=400", "True",  "NULL"],
    ],
    col_widths=[0.4, 1.3, 1.4, 0.9, 1.3, 1.3, 0.8, 1.5],
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 10 — AUTH
# ═════════════════════════════════════════════════════════════════════════════

h1("10.  Auth Table")
h2("10.1  password_reset_tokens")
para("One-time password reset tokens. The raw token is emailed to the user; only its SHA-256 hash is stored. On reset, the system hashes the submitted token and compares it to token_hash. Once used, used_at is set so the same link cannot be reused. Rows are CASCADE deleted when the parent user is deleted.", size=10)
blank()

make_table(
    headers=["Column", "Type", "Nullable", "Default", "Constraints", "Description"],
    rows=[
        ["id",         "Integer",     "No",  "auto-increment", "PK + INDEX",                  "Unique token identifier"],
        ["user_id",    "Integer",     "No",  "—",              "FK → users.id  CASCADE  INDEX","Parent user — deleted with user"],
        ["token_hash", "String(128)", "No",  "—",              "UNIQUE + INDEX",               "SHA-256 hash of the raw reset token"],
        ["expires_at", "DateTime",    "No",  "—",              "INDEX",                        "Token expires at this UTC timestamp"],
        ["used_at",    "DateTime",    "Yes", "NULL",           "—",                            "Set when consumed — NULL means token is still valid"],
        ["created_at", "DateTime",    "No",  "utcnow",         "—",                            "Creation timestamp"],
    ],
    col_widths=[1.2, 1.0, 0.7, 1.1, 2.0, 3.5],
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 11 — FK CHAIN WALKTHROUGHS
# ═════════════════════════════════════════════════════════════════════════════

h1("11.  FK Chain Walkthroughs")
para("Step-by-step traces showing how the foreign keys connect at runtime.", size=10)
blank()

h2("11.1  What is Camera 1 (Gate 1) actively detecting?")
code(
    "cameras.id = 1  (Gate 1)\n"
    "  │\n"
    "  └──► camera_model_assignments  WHERE camera_id = 1  AND is_enabled = True\n"
    "            │\n"
    "            ├── id=1  model_id=1  ──► ai_models: ppe_model  (weights/best (3).pt)\n"
    "            │       │\n"
    "            │       └──► camera_class_configs  WHERE assignment_id = 1  AND is_active = True\n"
    "            │                 class_id=3   ──► model_classes: Hardhat       role=safe\n"
    "            │                 class_id=7   ──► model_classes: NO-Hardhat    role=violation ✓ ALERT\n"
    "            │                 class_id=10  ──► model_classes: Safety Vest   role=safe\n"
    "            │                 class_id=8   ──► model_classes: NO-Safety Vest role=violation ✓ ALERT\n"
    "            │                 (class_id=2 Gloves      is_active=False → SILENCED)\n"
    "            │                 (class_id=6 NO-Gloves   is_active=False → SILENCED)\n"
    "            │\n"
    "            └── id=2  model_id=2  ──► ai_models: vehicle_model  (weights/vehicle.pt)\n"
    "                    │\n"
    "                    └──► camera_class_configs  WHERE assignment_id = 2  AND is_active = True\n"
    "                              class_id=11  ──► model_classes: Car    role=neutral\n"
    "                              class_id=12  ──► model_classes: Bus    role=neutral\n"
    "                              (class_id=13 Bike  is_active=False → SILENCED)\n"
    "\n"
    "Result:  Gate 1 is detecting → Hardhat, NO-Hardhat, Safety Vest, NO-Safety Vest, Car, Bus"
)

blank()
h2("11.2  Which buzzers sound when Gate 1 fires a violation?")
code(
    "cameras.id = 1  (Gate 1)\n"
    "  │\n"
    "  └──► camera_buzzers  WHERE camera_id = 1\n"
    "            buzzer_id=1  ──► buzzers.id=1: Gate Buzzer    (USB  /dev/ttyACM0)\n"
    "            buzzer_id=3  ──► buzzers.id=3: Office Buzzer  (MQTT 192.168.1.51:1883)\n"
    "\n"
    "Result:  Both Gate Buzzer and Office Buzzer activate simultaneously."
)

blank()
h2("11.3  Who acknowledged Alert #2, and when?")
code(
    "alerts.id = 2\n"
    "  acknowledged    = True\n"
    "  acknowledged_by = 2  ──► users.id=2: raj  (role=operator)\n"
    "  acknowledged_at = 2026-05-05 10:35 UTC"
)

blank()
h2("11.4  Is the burglar alarm active for Warehouse right now at 21:00?")
code(
    "cameras.id = 3  (Warehouse)\n"
    "  │\n"
    "  └──► burglar_alarm_configs  WHERE camera_id = 3\n"
    "            alarm_enabled    = True          ✓ check 1 passed\n"
    "            alarm_start_time = 18:00\n"
    "            alarm_end_time   = 07:00\n"
    "            current time     = 21:00         ✓ check 2 passed (within 18:00 – 07:00 window)\n"
    "            monitored_zone_id = uuid-wh-zone ──► rois.roi_id=uuid-wh-zone  is_active=True\n"
    "\n"
    "  If a Person class is detected inside uuid-wh-zone:\n"
    "            ✓ check 3 passed  →  ALARM FIRES\n"
    "            burglar_alarm_events row is written\n"
    "            cooldown_sec = 60  →  alarm cannot fire again for 60 seconds"
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 12 — CASCADE DELETE RULES
# ═════════════════════════════════════════════════════════════════════════════

h1("12.  Cascade Delete Rules")
para("What happens in the database when each root-level row is deleted.", size=10)
blank()

h2("12.1  Delete a cameras row")
code(
    "DELETE cameras WHERE id = 1\n"
    "  ├── CASCADE  → camera_model_assignments (camera_id=1) rows deleted\n"
    "  │                   └── CASCADE  → camera_class_configs (assignment_id=1,2) rows deleted\n"
    "  ├── CASCADE  → camera_buzzers (camera_id=1) rows deleted\n"
    "  ├── CASCADE  → rois (camera_id=1) rows deleted\n"
    "  ├── CASCADE  → burglar_alarm_configs (camera_id=1) row deleted\n"
    "  ├── SET NULL → alerts.camera_id = NULL              (alert rows kept — history preserved)\n"
    "  └── SET NULL → burglar_alarm_events.camera_id = NULL (event rows kept — history preserved)"
)

blank()
h2("12.2  Delete an ai_models row")
code(
    "DELETE ai_models WHERE id = 1  (ppe_model)\n"
    "  ├── CASCADE  → model_classes (model_id=1) rows deleted\n"
    "  │                   └── CASCADE  → camera_class_configs referencing those classes deleted\n"
    "  └── CASCADE  → camera_model_assignments (model_id=1) rows deleted\n"
    "                       └── CASCADE  → camera_class_configs (assignment_id) rows deleted"
)

blank()
h2("12.3  Delete a users row")
code(
    "DELETE users WHERE id = 2  (raj)\n"
    "  ├── CASCADE  → password_reset_tokens (user_id=2) deleted\n"
    "  ├── SET NULL → alerts.acknowledged_by = NULL              (audit trail kept)\n"
    "  └── SET NULL → burglar_alarm_events.acknowledged_by = NULL (audit trail kept)"
)

blank()
h2("12.4  Delete a buzzers row")
code(
    "DELETE buzzers WHERE id = 1  (Gate Buzzer)\n"
    "  └── CASCADE  → camera_buzzers (buzzer_id=1) rows deleted"
)

blank()
h2("12.5  Delete a camera_model_assignments row")
code(
    "DELETE camera_model_assignments WHERE id = 1  (Gate1 + PPE)\n"
    "  └── CASCADE  → camera_class_configs (assignment_id=1) rows deleted\n"
    "                 (Gate 1 no longer has any PPE class configs — PPE model is unassigned)"
)

doc.add_page_break()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 13 — USEFUL SQL QUERIES
# ═════════════════════════════════════════════════════════════════════════════

h1("13.  Useful SQL Queries")

h2("Get all active classes for a specific camera")
code(
    "SELECT\n"
    "    c.name              AS camera_name,\n"
    "    m.name              AS model_name,\n"
    "    mc.class_name,\n"
    "    mc.class_role,\n"
    "    mc.trigger_alert\n"
    "FROM cameras c\n"
    "JOIN camera_model_assignments cma  ON cma.camera_id = c.id     AND cma.is_enabled = TRUE\n"
    "JOIN ai_models m                   ON m.id = cma.model_id       AND m.is_active = TRUE\n"
    "JOIN camera_class_configs ccc      ON ccc.assignment_id = cma.id AND ccc.is_active = TRUE\n"
    "JOIN model_classes mc              ON mc.id = ccc.class_id\n"
    "WHERE c.id = 1;\n"
    "-- Returns: all classes Gate 1 will detect and alert on"
)

blank()
h2("Get all unacknowledged violation alerts in the last 24 hours")
code(
    "SELECT\n"
    "    a.id,\n"
    "    c.name              AS camera_name,\n"
    "    a.violation_type,\n"
    "    a.confidence_score,\n"
    "    a.triggered_at,\n"
    "    a.snapshot_path\n"
    "FROM alerts a\n"
    "LEFT JOIN cameras c ON c.id = a.camera_id\n"
    "WHERE a.acknowledged = FALSE\n"
    "  AND a.triggered_at >= NOW() - INTERVAL '24 hours'\n"
    "ORDER BY a.triggered_at DESC;"
)

blank()
h2("Get all buzzer assignments for a camera")
code(
    "SELECT\n"
    "    c.name  AS camera_name,\n"
    "    b.name  AS buzzer_name,\n"
    "    b.protocol,\n"
    "    b.ip_address,\n"
    "    b.device_id\n"
    "FROM camera_buzzers cb\n"
    "JOIN cameras c ON c.id = cb.camera_id\n"
    "JOIN buzzers b ON b.id = cb.buzzer_id\n"
    "WHERE cb.camera_id = 1;"
)

blank()
h2("Toggle a specific class off for a camera")
code(
    "-- Silence 'NO-Gloves' on Gate 1 (PPE model assignment id=1, class id=6)\n"
    "UPDATE camera_class_configs\n"
    "SET    is_active  = FALSE,\n"
    "       updated_at = NOW()\n"
    "WHERE  assignment_id = 1    -- Gate1 + PPE assignment\n"
    "  AND  class_id      = 6;   -- NO-Gloves class"
)

blank()
h2("Assign a new model to a camera and enable all its classes")
code(
    "-- Step 1: create assignment\n"
    "INSERT INTO camera_model_assignments (camera_id, model_id, is_enabled)\n"
    "VALUES (2, 3, TRUE);   -- Parking + fire_model\n"
    "\n"
    "-- Step 2: create class configs for all classes of that model\n"
    "INSERT INTO camera_class_configs (assignment_id, class_id, is_active)\n"
    "SELECT currval('camera_model_assignments_id_seq'), mc.id, TRUE\n"
    "FROM   model_classes mc\n"
    "WHERE  mc.model_id = 3;  -- all fire_model classes"
)

blank()
h2("Get daily alert summary per camera")
code(
    "SELECT\n"
    "    c.name                   AS camera_name,\n"
    "    a.violation_type,\n"
    "    COUNT(*)                 AS total_alerts,\n"
    "    COUNT(*) FILTER (WHERE a.acknowledged = TRUE)  AS acknowledged,\n"
    "    COUNT(*) FILTER (WHERE a.acknowledged = FALSE) AS pending\n"
    "FROM alerts a\n"
    "LEFT JOIN cameras c ON c.id = a.camera_id\n"
    "WHERE DATE(a.triggered_at) = CURRENT_DATE\n"
    "GROUP BY c.name, a.violation_type\n"
    "ORDER BY total_alerts DESC;"
)

blank()
blank()
divider()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_run(p, "SkyAI Technologies  ·  Confidential  ·  May 2026", size=9, color=C_GREY, italic=True)


# ── Save ──────────────────────────────────────────────────────────────────────
out = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "schema_relationships.docx")
)
os.makedirs(os.path.dirname(out), exist_ok=True)
doc.save(out)
print(f"Saved → {out}")
