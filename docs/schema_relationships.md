# Database Schema — Full Relationship Diagram

## Quick Reference: All Foreign Keys

| Table | Column | References |
|---|---|---|
| `camera_model_assignments` | `camera_id` | `cameras.id` CASCADE DELETE |
| `camera_model_assignments` | `model_id` | `ai_models.id` CASCADE DELETE |
| `camera_class_configs` | `assignment_id` | `camera_model_assignments.id` CASCADE DELETE |
| `camera_class_configs` | `class_id` | `model_classes.id` CASCADE DELETE |
| `model_classes` | `model_id` | `ai_models.id` CASCADE DELETE |
| `camera_buzzers` | `camera_id` | `cameras.id` CASCADE DELETE |
| `camera_buzzers` | `buzzer_id` | `buzzers.id` CASCADE DELETE |
| `rois` | `camera_id` | `cameras.id` CASCADE DELETE |
| `burglar_alarm_configs` | `camera_id` | `cameras.id` CASCADE DELETE |
| `alerts` | `camera_id` | `cameras.id` SET NULL |
| `alerts` | `acknowledged_by` | `users.id` SET NULL |
| `burglar_alarm_events` | `camera_id` | `cameras.id` SET NULL |
| `burglar_alarm_events` | `acknowledged_by` | `users.id` SET NULL |
| `password_reset_tokens` | `user_id` | `users.id` CASCADE DELETE |

---

## Full Schema Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                  cameras                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│  id (PK)  │  name      │  stream_url         │  location  │  is_active       │
│  1        │  Gate 1    │  rtsp://192.168.1.10 │  Main Gate │  True            │
│  2        │  Parking   │  rtsp://192.168.1.11 │  Lot B     │  True            │
│  3        │  Warehouse │  rtsp://192.168.1.12 │  Floor 1   │  True            │
└─────┬─────┴────────────┴─────────────────────┴────────────┴──────────────────┘
      │ PK: id
      │
      ├─────────────────────────────────────────────────────────────────────────────────────────────────────┐
      │                                                                                                     │
      │  camera_id FK ─────────────────────────────────────────────────────────┐                           │ camera_id FK
      │                                                                         │                           │
      │                                                                         │                           │
┌─────▼─────────────────────────────────────────────┐              ┌────────────▼──────────────┐  ┌────────▼─────────────────┐
│              camera_model_assignments              │              │       camera_buzzers       │  │           rois           │
├───────────────────────────────────────────────────┤              ├───────────────────────────┤  ├──────────────────────────┤
│ id │ camera_id │ model_id │ is_enabled │ threshold │              │ id │ camera_id │ buzzer_id │  │ roi_id │ camera_id │ name │
│ 1  │     1     │    1     │   True     │   NULL    │              │ 1  │     1     │     1     │  │ uuid-1 │     1     │ Gate │
│ 2  │     1     │    2     │   True     │   NULL    │              │ 2  │     1     │     3     │  │ uuid-2 │     2     │ Park │
│ 3  │     2     │    2     │   True     │   0.40    │              │ 3  │     2     │     2     │  │ uuid-3 │     3     │ WH-1 │
│ 4  │     3     │    1     │   True     │   NULL    │              └─────────────┬─────────────┘  └──────────────────────────┘
│ 5  │     3     │    3     │   True     │   0.60    │                            │ buzzer_id FK
└──┬──────────────────┬──────────────────────────────┘                           │
   │ PK: id           │ model_id FK                               ┌──────────────▼───────────────────────┐
   │                  │                                           │                buzzers                │
   │ assignment_id FK │                                           ├───────────────────────────────────────┤
   │                  │                                           │ id │ name           │ protocol │ port │
   │          ┌───────▼──────────────────────────────────┐       │ 1  │ Gate Buzzer    │ usb      │ NULL │
   │          │                ai_models                  │       │ 2  │ Floor Buzzer   │ http     │ 8080 │
   │          ├───────────────────────────────────────────┤       │ 3  │ Office Buzzer  │ mqtt     │ 1883 │
   │          │ id │ name          │ weight_path    │imgsz│       └───────────────────────────────────────┘
   │          │ 1  │ ppe_model     │ weights/b3.pt  │ 640 │
   │          │ 2  │ vehicle_model │ weights/veh.pt │ 640 │
   │          │ 3  │ fire_model    │ weights/fir.pt │ 640 │
   │          └────────────┬──────────────────────────────┘
   │                       │ model_id FK
   │                       │
   │          ┌────────────▼──────────────────────────────────────────┐
   │          │                    model_classes                       │
   │          ├───────────────────────────────────────────────────────┤
   │          │ id │ model_id │ class_index │ class_name   │ role      │
   │          │ 1  │    1     │      3      │ Hardhat      │ safe      │
   │          │ 2  │    1     │      8      │ NO-Hardhat   │ violation │
   │          │ 3  │    1     │      1      │ Gloves       │ safe      │
   │          │ 4  │    1     │      6      │ NO-Gloves    │ violation │
   │          │ 5  │    1     │     13      │ Safety Vest  │ safe      │
   │          │ 6  │    1     │     10      │ NO-Vest      │ violation │
   │          │ 7  │    2     │      0      │ Car          │ neutral   │
   │          │ 8  │    2     │      1      │ Bus          │ neutral   │
   │          │ 9  │    2     │      2      │ Bike         │ neutral   │
   │          │ 10 │    3     │      0      │ Fire         │ violation │
   │          │ 11 │    3     │      1      │ Smoke        │ violation │
   │          └──────────────────────────┬────────────────────────────┘
   │                                     │ class_id FK
   │                                     │
┌──▼──────────────────────────────────────▼─────────────────┐
│                   camera_class_configs                      │
├─────────────────────────────────────────────────────────────┤
│ id │ assignment_id │ class_id │ is_active                   │
│ 1  │      1        │    1     │ True    (Gate1+PPE+Hardhat)  │
│ 2  │      1        │    2     │ True    (Gate1+PPE+NO-Hard)  │
│ 3  │      1        │    3     │ False   (Gate1+PPE+Gloves)   │
│ 4  │      1        │    4     │ False   (Gate1+PPE+NO-Glove) │
│ 5  │      2        │    7     │ True    (Gate1+VEH+Car)      │
│ 6  │      2        │    8     │ True    (Gate1+VEH+Bus)      │
│ 7  │      2        │    9     │ False   (Gate1+VEH+Bike)     │
│ 8  │      4        │    1     │ True    (WH+PPE+Hardhat)     │
│ 9  │      5        │   10     │ True    (WH+Fire+Fire)       │
│ 10 │      5        │   11     │ True    (WH+Fire+Smoke)      │
└─────────────────────────────────────────────────────────────┘
```

---

## Event Logs

```
camera_id SET NULL when camera deleted — historical records always preserved

┌──────────────────────────────────────────────────────────────────────┐
│                              alerts                                   │
├──────────────────────────────────────────────────────────────────────┤
│ id │ camera_id │ violation_type │ confidence │ ack'd │ ack'd_by      │
│ 1  │     1     │ NO-Hardhat     │   0.87     │ False │  NULL         │
│ 2  │     1     │ NO-Hardhat     │   0.91     │ True  │   2  ─────────┼──┐
│ 3  │     2     │ Car            │   0.76     │ False │  NULL         │  │
│ 4  │  NULL ◄───┼─ camera deleted│   0.80     │ True  │   1  ─────────┼──┤
└────┴─────┬─────┴────────────────┴────────────┴───────┴───────────────┘  │
           │ camera_id FK → cameras.id (SET NULL)                          │
           │                                                               │
┌──────────┴──────────────────────────────────────────────────────────┐    │
│                       burglar_alarm_events                           │    │
├──────────────────────────────────────────────────────────────────────┤    │
│ id │ camera_id │ zone_id  │ confidence │ bbox_x1 │ bbox_x2 │ ack'd  │    │
│ 1  │     1     │ uuid-1   │   0.88     │  120    │   200   │ False  │    │
│ 2  │     2     │  NULL    │   0.79     │  300    │   410   │ True   ├────┘
└────┴─────┬─────┴──────────┴────────────┴─────────┴─────────┴────────┘
           │ camera_id FK → cameras.id (SET NULL)                     │
           │                                                          │ ack'd_by FK → users.id (SET NULL)
           │                                                          │
┌──────────┴──────────────────────────────────────────────────────────▼──────┐
│                                   users                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│ id │ username  │ role      │ is_active                                        │
│ 1  │ admin     │ admin     │ True                                             │
│ 2  │ raj       │ operator  │ True                                             │
│ 3  │ krishnam  │ operator  │ True                                             │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ user_id FK CASCADE DELETE
                               │
             ┌─────────────────▼──────────────────────────────┐
             │              password_reset_tokens              │
             ├────────────────────────────────────────────────┤
             │ id │ user_id │ token_hash   │ expires_at │ used │
             │ 1  │    2    │ sha256:ab... │ 2026-05-05 │ NULL │
             └────────────────────────────────────────────────┘
```

---

## Burglar Alarm Config (1:1 with Camera)

```
┌──────────────────────────────────┐
│            cameras               │
│  id=1  Gate 1                    │
│  id=2  Parking                   │
│  id=3  Warehouse                 │
└──────────────┬───────────────────┘
               │ camera_id FK (UNIQUE — one config per camera)
               │
┌──────────────▼──────────────────────────────────────────────┐
│                    burglar_alarm_configs                      │
├──────────────────────────────────────────────────────────────┤
│ id │ camera_id │ enabled │ start │ end   │ zone_id  │cooldown│
│ 1  │     1     │  True   │ 20:00 │ 06:00 │ uuid-1   │  30s   │
│ 2  │     2     │  False  │ 20:00 │ 06:00 │  NULL    │  30s   │
│ 3  │     3     │  True   │ 18:00 │ 07:00 │ uuid-3   │  60s   │
└──────────────────────────────────────────────────────────────┘
```

---

## How to Read the FK Chain

### "What is Camera 1 detecting right now?"

```
cameras.id = 1  (Gate 1)
    │
    └──► camera_model_assignments WHERE camera_id = 1
              │
              ├── row id=1  →  model_id=1  →  ai_models: "ppe_model"
              │       │
              │       └──► camera_class_configs WHERE assignment_id = 1
              │                   class_id=1 is_active=True   →  model_classes id=1: Hardhat (safe)
              │                   class_id=2 is_active=True   →  model_classes id=2: NO-Hardhat (violation)
              │                   class_id=3 is_active=False  →  Gloves (ignored)
              │                   class_id=4 is_active=False  →  NO-Gloves (ignored)
              │
              └── row id=2  →  model_id=2  →  ai_models: "vehicle_model"
                      │
                      └──► camera_class_configs WHERE assignment_id = 2
                                  class_id=7 is_active=True   →  model_classes id=7: Car (neutral)
                                  class_id=8 is_active=True   →  model_classes id=8: Bus (neutral)
                                  class_id=9 is_active=False  →  Bike (ignored)
```

**Answer:** Gate 1 is detecting Hardhat, NO-Hardhat, Car, Bus.

---

### "Which buzzers fire when Gate 1 gets a violation?"

```
cameras.id = 1
    └──► camera_buzzers WHERE camera_id = 1
              buzzer_id=1  →  buzzers id=1: "Gate Buzzer"  (usb /dev/ttyACM0)
              buzzer_id=3  →  buzzers id=3: "Office Buzzer" (mqtt)
```

**Answer:** Both Gate Buzzer and Office Buzzer fire.

---

## Cascade Delete Summary

```
DELETE cameras row
    ├── CASCADE → camera_model_assignments deleted
    │                 └── CASCADE → camera_class_configs deleted
    ├── CASCADE → camera_buzzers deleted
    ├── CASCADE → rois deleted
    ├── CASCADE → burglar_alarm_configs deleted
    ├── SET NULL → alerts.camera_id = NULL  (history kept)
    └── SET NULL → burglar_alarm_events.camera_id = NULL  (history kept)

DELETE ai_models row
    ├── CASCADE → camera_model_assignments deleted
    │                 └── CASCADE → camera_class_configs deleted
    └── CASCADE → model_classes deleted
                      └── CASCADE → camera_class_configs deleted

DELETE users row
    ├── CASCADE → password_reset_tokens deleted
    ├── SET NULL → alerts.acknowledged_by = NULL
    └── SET NULL → burglar_alarm_events.acknowledged_by = NULL

DELETE buzzers row
    └── CASCADE → camera_buzzers deleted
```
