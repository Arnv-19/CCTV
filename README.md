# SkyCCTVAI

A real-time CCTV AI automation platform. Ingests multiple RTSP camera streams, runs YOLOv8 detection models on each stream, logs violations to PostgreSQL, and triggers configurable alarms (USB serial, HTTP/ESP32, GPIO, or MQTT) when violations are detected.

---

## Features

- **Live MJPEG streaming** — browser-side camera feed with bounding boxes and FPS overlay
- **YOLOv8 detection** — per-camera AI model inference with confidence threshold control
- **Multi-transport alarms** — USB serial, HTTP (ESP32), MQTT, or GPIO buzzers
- **Database-backed alert log** — violations stored in PostgreSQL with snapshot images
- **JWT authentication** — role-based access control (admin / operator)
- **Buzzer management** — create and assign physical buzzer devices to cameras
- **Per-camera model selection** — enable/disable AI models per camera at runtime
- **Reports & CSV export** — filterable alert history with acknowledgement workflow
- **Non-blocking alert pipeline** — camera threads never block on DB writes (queue-based)

---

## Architecture

```
Browser (React + Vite + Tailwind)
    │  JWT auth  ·  REST API  ·  Live MJPEG streams
    ▼
FastAPI Server (app/main.py)
    ├── /api/auth            Login → JWT token
    ├── /api/users           User management  (admin only)
    ├── /api/cameras         Camera CRUD + start/stop
    ├── /api/stream/{id}     Async MJPEG generator
    ├── /api/config          Read/write config.yaml
    ├── /api/buzzers         Buzzer device CRUD
    ├── /api/camera-buzzers  Camera ↔ buzzer assignments
    ├── /api/camera-models   Per-camera AI model toggles
    ├── /api/alerts          Violation log, summary, CSV export
    ├── /api/alarm           Test alarm + transport status
    └── /api/logs            Read/clear alerts.log (legacy)
    │
    ▼
CameraManager  (app/services/camera_manager.py)
    ├── Thread per camera → camera_worker.camera_loop()
    │       ├── cv2.VideoCapture  (RTSP)
    │       ├── detector.run_detection  (YOLOv8)
    │       ├── fire_buzzers()  (DB-assigned buzzers)
    │       └── alert_queue.put()  (non-blocking DB log)
    ├── AlertWriter thread  →  PostgreSQL (via alert_queue)
    └── frame_dict  {cam_id: JPEG bytes}  ◄── streamed to UI
    │
    ▼
PostgreSQL  (app/db/)
    ├── users
    ├── buzzers
    ├── camera_buzzers
    ├── camera_models
    └── alerts
```

---

## Project Structure

```
SkyCCTVAI/
├── app/                              # FastAPI application package
│   ├── main.py                       # App factory, CORS, lifespan, route mounts
│   ├── config.py                     # config.yaml load/save helpers + defaults
│   ├── dependencies.py               # get_current_user, require_admin
│   ├── db/
│   │   ├── database.py               # SQLAlchemy engine + SessionLocal + get_db
│   │   ├── models.py                 # ORM models: User, Buzzer, CameraBuzzer,
│   │   │                             #   CameraModel, Alert
│   │   └── init_db.py                # Create tables + seed default admin user
│   ├── services/
│   │   ├── camera_manager.py         # Singleton: threads, AlertWriter, frame_dict
│   │   └── auth_service.py           # bcrypt hashing, JWT create/decode
│   └── api/routes/
│       ├── auth.py                   # POST /api/auth/login  GET /api/auth/me
│       ├── users.py                  # Admin CRUD for user accounts
│       ├── cameras.py                # Camera CRUD + start/stop endpoints
│       ├── config_routes.py          # GET/PATCH /api/config
│       ├── buzzers.py                # Buzzer device CRUD
│       ├── camera_buzzers.py         # Camera ↔ buzzer assignment
│       ├── camera_models.py          # Per-camera AI model toggles
│       ├── alerts.py                 # Alert log, summary, acknowledge, CSV export
│       ├── alarm.py                  # POST /api/alarm/test  GET /api/alarm/status
│       ├── logs.py                   # GET/DELETE /api/logs  (legacy flat-file log)
│       └── stream.py                 # GET /api/stream/{cam_id}  (MJPEG)
│
├── camera_worker.py                  # Per-camera capture + detection loop (thread)
├── detector.py                       # YOLOv8 model loader and inference wrapper
├── alarm.py                          # Multi-transport alarm sender (USB/HTTP/MQTT/GPIO)
├── config.yaml                       # Runtime configuration (cameras, model, alarm)
├── .env.example                      # Environment variable template
├── run_server.sh                     # Quick-start script for the FastAPI server
├── requirements.txt                  # Python dependencies
│
├── frontend/                         # React 18 + Vite + Tailwind CSS
│   ├── src/
│   │   ├── main.jsx                  # Entry: AuthProvider + BrowserRouter + Routes
│   │   ├── App.jsx                   # Auth guard, tabs, start/stop, toast
│   │   ├── contexts/
│   │   │   └── AuthContext.jsx       # JWT storage, login/logout, isAdmin
│   │   ├── pages/
│   │   │   └── LoginPage.jsx         # Login form → POST /api/auth/login
│   │   ├── api/client.js             # Typed fetch wrappers (auth header, 401 handler)
│   │   └── components/
│   │       ├── LiveView.jsx          # Dynamic camera grid layout
│   │       ├── CameraCard.jsx        # MJPEG stream card with stats overlay
│   │       ├── ConfigPanel.jsx       # Config + buzzer assignment + model toggles
│   │       ├── ReportsPanel.jsx      # Filterable alert table, CSV export, ack
│   │       ├── BuzzersPanel.jsx      # Buzzer device CRUD (admin)
│   │       ├── UsersPanel.jsx        # User management (admin)
│   │       ├── LogsPanel.jsx         # Auto-refreshing alerts.log viewer
│   │       └── AlarmPanel.jsx        # Transport status + test alarm button
│   ├── vite.config.js                # Dev proxy: /api → localhost:8000
│   └── package.json
│
├── data/class_names.yaml             # YOLO class list + helmet/no_helmet labels
├── weights/helmet_model.pt           # YOLOv8 model weights
├── snapshots/                        # Violation snapshot JPEGs (cam_id/violation_*.jpg)
├── logs/alerts.log                   # Flat-file violation log (legacy)
└── ESP/ESP.ino                       # Arduino firmware for ESP32 buzzer controller
```

---

## Setup

### 1. Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. PostgreSQL database

Create a database and user, then copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env — set DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, JWT_SECRET
```

Initialize tables and create the default admin account:

```bash
python -m app.db.init_db
# Default credentials come from .env: DEFAULT_ADMIN_USER / DEFAULT_ADMIN_PASSWORD
# (defaults: admin / Admin@1234 — change immediately after first login)
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. USB serial port (ESP32 via USB, optional)

```bash
sudo dmesg | grep tty          # find the port, e.g. /dev/ttyACM0
```

Update `SERIAL_PORT` in `alarm.py` or set `alarm_transport: http` / `mqtt` in `config.yaml` to skip serial.

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `skycctvai` | Database name |
| `DB_USER` | — | Database user |
| `DB_PASSWORD` | — | Database password |
| `JWT_SECRET` | — | Secret key for signing JWT tokens (use a long random string) |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | `480` | Token lifetime (8 hours) |
| `DEFAULT_ADMIN_USER` | `admin` | Username seeded by `init_db` |
| `DEFAULT_ADMIN_EMAIL` | — | Email seeded by `init_db` |
| `DEFAULT_ADMIN_PASSWORD` | `Admin@1234` | Password seeded by `init_db` |
| `SNAPSHOT_DIR` | `snapshots` | Directory for violation snapshot JPEGs |

---

## Running

### Development (two terminals)

**Terminal 1 — FastAPI backend:**
```bash
./run_server.sh
# or: .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — React dev server:**
```bash
cd frontend
npm run dev
# opens http://localhost:5173  (API calls proxied to :8000)
```

### Production

```bash
cd frontend && npm run build        # outputs to frontend/dist/
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# FastAPI serves the React build from frontend/dist/ at /
```

Interactive API docs: `http://localhost:8000/docs`

---

## Configuration (`config.yaml`)

```yaml
# Camera streams
camera_feeds:
  - rtsp://user:pass@192.168.1.10:554/Streaming/Channels/101
camera_titles:
  - Ground Floor

# YOLOv8 model
model_path: weights/helmet_model.pt
class_file: data/class_names.yaml
confidence_threshold: 0.25          # 0.0–1.0

# Alarm cooldown: min seconds between alarms per camera (0 = every frame)
alarm_cooldown_sec: 10

# Alarm transport: usb | http | mqtt | gpio
# If not set, falls back to: use_wifi=true => http, else usb
alarm_transport: usb

# HTTP transport (ESP32 web server)
use_wifi: false
esp_ip: 192.168.1.100
alarm_http_token: ""                # optional ?token= param

# MQTT transport (set alarm_transport: mqtt to activate)
mqtt_broker: ""
mqtt_port: 1883
mqtt_topic: skycctv/alarm
mqtt_username: ""
mqtt_password: ""
mqtt_client_id: skycctv-ai
mqtt_qos: 1
mqtt_retain: false
```

Buzzer assignments and per-camera model selection are managed via the web UI and stored in PostgreSQL, not in `config.yaml`.

---

## Alarm Transports

| Transport | How it works | When to use |
|-----------|-------------|-------------|
| `usb` | Sends `buzz_on\n` over USB serial to ESP32 | Direct USB cable |
| `http` | `GET http://<ip>/buzz_on` | ESP32 on same WiFi network |
| `mqtt` | Publishes JSON to `<mqtt_topic>` | Remote broker / smart home |
| `gpio` | Toggles a Raspberry Pi GPIO pin | GPIO-connected buzzer |

All transports are non-blocking — alarm delivery runs in a background thread so it never delays the detection loop.

---

## API Reference

### Authentication
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/login` | — | Login → `{ access_token, role }` |
| GET | `/api/auth/me` | Any | Current user info |

### Users (admin only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users/` | List all users |
| POST | `/api/users/` | Create user |
| PATCH | `/api/users/{id}` | Update email / role / active status |
| DELETE | `/api/users/{id}` | Deactivate user |
| POST | `/api/users/{id}/reset-password` | Set new password |

### Cameras
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cameras/` | List cameras with status, FPS, violations |
| POST | `/api/cameras/` | Add a camera |
| PUT | `/api/cameras/{id}` | Update camera URL / title |
| DELETE | `/api/cameras/{id}` | Remove a camera |
| POST | `/api/cameras/start` | Start detection on all cameras |
| POST | `/api/cameras/stop` | Stop all detection |
| POST | `/api/cameras/{id}/start` | Start single camera |
| POST | `/api/cameras/{id}/stop` | Stop single camera |
| GET | `/api/stream/{cam_id}` | MJPEG stream (use as `<img src>`) |

### Buzzers (admin write, all read)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/buzzers/` | List all buzzers |
| POST | `/api/buzzers/` | Create buzzer |
| PUT | `/api/buzzers/{id}` | Update buzzer |
| DELETE | `/api/buzzers/{id}` | Delete buzzer |
| PATCH | `/api/buzzers/{id}/toggle` | Enable / disable buzzer |

### Camera ↔ Buzzer Assignments (admin write)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/camera-buzzers/{camera_id}` | List assigned buzzers |
| POST | `/api/camera-buzzers/{camera_id}/{buzzer_id}` | Assign buzzer |
| DELETE | `/api/camera-buzzers/{camera_id}/{buzzer_id}` | Unassign buzzer |
| PUT | `/api/camera-buzzers/{camera_id}` | Replace full buzzer set |

### Per-Camera AI Models
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/camera-models/{camera_id}` | List model flags for camera |
| POST | `/api/camera-models/{camera_id}` | Upsert model enable/disable flag |
| PATCH | `/api/camera-models/{id}/toggle` | Toggle a model flag |
| GET | `/api/camera-models/{camera_id}/enabled` | List enabled model names |

### Alerts / Reports
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/alerts/` | Paginated alert list with filters |
| GET | `/api/alerts/summary` | Today count, unacknowledged, top camera/model |
| POST | `/api/alerts/` | Create alert (internal use) |
| PATCH | `/api/alerts/{id}/acknowledge` | Mark alert as reviewed |
| GET | `/api/alerts/export` | Download filtered alerts as CSV |

**Alert filters:** `camera_id`, `model_name`, `date_from`, `date_to`, `acknowledged`, `skip`, `limit`

### Config & Utilities
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config/` | Read full config.yaml |
| PATCH | `/api/config/` | Update config fields |
| POST | `/api/alarm/test` | Trigger alarm once (for testing) |
| GET | `/api/alarm/status` | Serial/WiFi/MQTT connection status |
| GET | `/api/logs/` | Recent alert log lines (`?lines=100`) |
| DELETE | `/api/logs/` | Clear alerts.log |

---

## User Roles

| Role | Permissions |
|------|-------------|
| `admin` | Full access: all read + write + user management + buzzer management |
| `operator` | Read access + camera start/stop + config view |

---

## Violation Pipeline

```
camera_loop (thread)
    │  violation detected → cooldown check
    ├── save_snapshot()        → snapshots/cam_N/violation_TIMESTAMP.jpg
    ├── fire_buzzers()         → assigned buzzers from DB (USB/HTTP/MQTT/GPIO)
    │   └── fallback: alarm.trigger_alarm()  if no DB buzzers assigned
    └── alert_queue.put({...}) → non-blocking

AlertWriter (background thread)
    └── reads queue → INSERT INTO alerts
```

Camera threads never block on DB writes. The AlertWriter drains the queue independently, so inference FPS is not affected by database latency.

---

## ESP32 Firmware

See [ESP/ESP.ino](ESP/ESP.ino). The firmware listens for:
- **USB:** serial commands `buzz_on\n` / `buzz_off\n`
- **WiFi:** HTTP `GET /buzz_on` and `GET /buzz_off`

Update WiFi credentials in the firmware before flashing via Arduino IDE.

---

## GPU Acceleration

`detector.py` uses `device='cuda'` by default. Change to `device='cpu'` in `detector.py` if no CUDA GPU is available.
