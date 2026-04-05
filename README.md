# 🚦 Synnex — Smart Traffic Management System

> Camera-based smart traffic controller built for **Raspberry Pi Zero 2W**.
> Uses OpenCV for real-time vehicle detection and counting — no heavy ML models.
> Round-robin signal scheduling with dynamic green-light duration based on traffic density.
> Full-featured web dashboard with live camera feed, manual override, and speed violation logging.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Vehicle Detection** | OpenCV background subtraction + contour analysis |
| **Traffic Density** | Real-time classification: LOW, MEDIUM, HIGH |
| **Round-Robin Scheduling** | Fair lane cycling with density-adaptive green durations |
| **Speed Estimation** | Frame-difference centroid tracking (camera-based) |
| **Speed Violations** | Logs vehicles exceeding configurable speed limit |
| **Web Dashboard** | Live camera, signal status, vehicle counts, manual override |
| **Automatic Mode** | Fully camera-driven signal decisions |
| **Manual Mode** | User controls lights from dashboard |
| **Data Logging** | SQLite database for counts, density, violations |
| **Auto-start** | Systemd service, restarts on crash |

---

## 🛒 Hardware Required

| Qty | Component |
|-----|-----------|
| 1 | Raspberry Pi Zero 2W |
| 1 | Pi Camera Module (v1.3 / v2 / HQ) |
| 6 | 5 mm LEDs — 2× Red, 2× Yellow, 2× Green |
| 6 | 220 Ω resistors (one per LED) |
| — | Jumper wires, breadboard / PCB |
| 1 | 5V / 2.5A USB-C power supply |

---

## 📌 GPIO Pin Mapping

### Traffic Light Wiring

| Signal | BCM GPIO | Physical Pin | Wire Colour |
|--------|----------|-------------|-------------|
| **Lane 1 — RED LED** | GPIO 5 | Pin 29 | Red |
| **Lane 1 — YELLOW LED** | GPIO 6 | Pin 31 | Yellow |
| **Lane 1 — GREEN LED** | GPIO 13 | Pin 33 | Green |
| **Lane 2 — RED LED** | GPIO 19 | Pin 35 | Red |
| **Lane 2 — YELLOW LED** | GPIO 26 | Pin 37 | Yellow |
| **Lane 2 — GREEN LED** | GPIO 21 | Pin 40 | Green |

### Pi Zero 2W Header Diagram

```
                    3V3  (1) (2)  5V
          SDA / GPIO 2  (3) (4)  5V
          SCL / GPIO 3  (5) (6)  GND
                GPIO 4  (7) (8)  GPIO 14
                   GND  (9)(10)  GPIO 15
                GPIO 17 (11)(12) GPIO 18
                GPIO 27 (13)(14) GND
                GPIO 22 (15)(16) GPIO 23
                   3V3 (17)(18) GPIO 24
                GPIO 10 (19)(20) GND
                GPIO  9 (21)(22) GPIO 25
                GPIO 11 (23)(24) GPIO  8
                   GND (25)(26) GPIO  7
  Lane1 RED  / GPIO 5  (29)(30) GND
  Lane1 YEL  / GPIO 6  (31)(32) GPIO 12
  Lane1 GRN  / GPIO13  (33)(34) GND
  Lane2 RED  / GPIO19  (35)(36) GPIO 16
  Lane2 YEL  / GPIO26  (37)(38) GPIO 20
                   GND (39)(40) GPIO 21  ← Lane2 GRN
```

> LED cathodes (–) connect to GND via **220 Ω resistor**.

---

## 📁 Project Structure

```
Synnex/
├── main.py                 ← Entry point — orchestrates all modules
├── camera.py               ← Video capture + OpenCV vehicle detection
├── traffic_controller.py   ← Round-robin signal scheduling
├── gpio_control.py         ← GPIO abstraction for traffic light LEDs
├── speed_detection.py      ← Camera-based speed estimation
├── dashboard.py            ← Flask web dashboard
├── data_logger.py          ← SQLite data persistence
├── requirements.txt        ← Python dependencies
├── install.sh              ← One-command Raspberry Pi setup
├── traffic_data.db         ← SQLite database (auto-created)
└── README.md               ← This file
```

---

## 🧠 System Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐
│  Pi Camera  │────▶│  camera.py       │────▶│  dashboard.py  │
│             │     │  Vehicle Detect  │     │  Flask Web UI  │
└─────────────┘     │  Density Count   │     │  MJPEG Stream  │
                    └────────┬─────────┘     │  REST API      │
                             │               └────────────────┘
                             ▼
                    ┌──────────────────┐     ┌────────────────┐
                    │ traffic_         │────▶│  gpio_control  │
                    │ controller.py    │     │  LED Lights    │
                    │ Round Robin      │     └────────────────┘
                    │ Density-Adaptive │
                    └──────────────────┘
                             │
                    ┌──────────────────┐     ┌────────────────┐
                    │ speed_           │────▶│  data_logger   │
                    │ detection.py     │     │  SQLite DB     │
                    │ Centroid Track   │     └────────────────┘
                    └──────────────────┘
```

---

## 🔄 Traffic Control Logic

```
Automatic Mode — Round-Robin with Density-Adaptive Timing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Lane 1 GREEN (duration based on density)
    │
    │  density = LOW    →  10 seconds green
    │  density = MEDIUM →  20 seconds green
    │  density = HIGH   →  35 seconds green
    │
    ├─ Time elapsed → Yellow blink → RED
    │
    ▼ (1s all-red safety gap)
    │
Lane 2 GREEN (same density logic)
    │
    └─ Repeat...
```

| Config Constant | Default | Meaning |
|---|---|---|
| `GREEN_DURATION["LOW"]` | `10s` | Green time for low traffic |
| `GREEN_DURATION["MEDIUM"]` | `20s` | Green time for moderate traffic |
| `GREEN_DURATION["HIGH"]` | `35s` | Green time for heavy traffic |
| `MIN_GREEN_SEC` | `8s` | Absolute minimum green time |
| `MAX_GREEN_SEC` | `45s` | Absolute maximum (prevents starvation) |
| `SPEED_LIMIT_KMPH` | `40` | Speed violation threshold |

---

## 🚀 Setup & Installation

### 1. Flash the Pi

Use **Raspberry Pi Imager** → Raspberry Pi OS Lite (64-bit).
In settings: enable SSH, set Wi-Fi SSID + password.

### 2. Transfer files

```bash
# From your PC
scp -r ./* pi@<PI_IP>:~/synnex/
```

### 3. Run the installer

```bash
ssh pi@<PI_IP>
cd ~/synnex
sudo bash install.sh
```

The installer will:
- Enable the camera interface
- Install system packages (`python3-picamera2`, `python3-opencv`)
- Create a Python venv at `~/synnex/venv/` (with system site-packages)
- Install `flask`, `RPi.GPIO`, `numpy` into the venv
- Register and start the `synnex-traffic` systemd service

### 4. Open the dashboard

```
http://<PI_IP>:5000
```

> ⚠ **First-time install**: reboot the Pi to enable the camera: `sudo reboot`

---

## ⚙️ Service Commands

```bash
sudo systemctl status  synnex-traffic    # check status
sudo systemctl restart synnex-traffic    # restart
sudo systemctl stop    synnex-traffic    # stop
sudo journalctl -u synnex-traffic -f     # live log stream
```

### Manual run (for development/testing)

```bash
source ~/synnex/venv/bin/activate
python main.py
python main.py --port 8080              # custom port
python main.py --no-speed               # disable speed detection (saves CPU)
```

---

## 🌐 Web Endpoints

| URL | Method | Description |
|-----|--------|-------------|
| `/` | GET | Live dashboard |
| `/stream` | GET | Raw MJPEG camera stream |
| `/api/state` | GET | Full system state (JSON) |
| `/api/mode` | POST | Switch mode `{"mode": "automatic"}` or `{"mode": "manual"}` |
| `/api/override` | POST | Manual override `{"lane": 1, "color": "green"}` |
| `/api/all_red` | POST | Emergency all-red |
| `/api/pins` | GET | GPIO pin mapping |
| `/api/violations` | GET | Speed violation history |
| `/api/stats` | GET | Aggregate statistics |

---

## 🐍 Python Dependencies

| Package | Source | Why |
|---------|--------|-----|
| `picamera2` | apt (system) | Pi Camera — pre-built for ARM |
| `opencv-python` | apt (system) | Frame processing + vehicle detection |
| `flask` | pip (venv) | Web server + MJPEG streaming + REST API |
| `RPi.GPIO` | pip (venv) | GPIO control for LEDs |
| `numpy` | pip/apt | Array operations for OpenCV |

> The venv uses `--system-site-packages` so `picamera2` and `opencv`
> (which are very slow to build from source on Pi Zero 2W) are
> reused from the system apt installation.

---

## 🔧 Customisation

### Camera Detection Tuning (`camera.py`)

```python
RESOLUTION       = (640, 480)     # capture resolution
PROCESS_SIZE     = (320, 240)     # downscaled for processing
CAMERA_FPS       = 10             # target FPS
MIN_CONTOUR_AREA = 800            # minimum area to detect a vehicle
DENSITY_LOW      = 3              # 0-3 vehicles/min → LOW
DENSITY_MEDIUM   = 8              # 4-8 vehicles/min → MEDIUM
```

### Lane ROI Configuration (`camera.py`)

```python
LANE_ROIS = {
    1: {"x1": 0.0,  "y1": 0.3, "x2": 0.48, "y2": 0.9},   # left half
    2: {"x1": 0.52, "y1": 0.3, "x2": 1.0,  "y2": 0.9},   # right half
}
```

### Speed Calibration (`speed_detection.py`)

```python
SPEED_LIMIT_KMPH = 40       # violation threshold
PIXELS_PER_METRE = 30.0     # MUST calibrate for your camera setup!
```

### Traffic Timing (`traffic_controller.py`)

```python
GREEN_DURATION = {
    "LOW":    10,       # seconds
    "MEDIUM": 20,
    "HIGH":   35,
}
MIN_GREEN_SEC = 8
MAX_GREEN_SEC = 45
```

---

## 📊 Data Storage

All data is stored in `traffic_data.db` (SQLite, auto-created).

| Table | Contents |
|-------|----------|
| `vehicle_counts` | Periodic snapshots of vehicle counts per lane |
| `density_log` | Traffic density readings (LOW/MEDIUM/HIGH) |
| `speed_violations` | Logged speed violations with timestamps |
| `signal_log` | Signal state changes with trigger reasons |

Old data is automatically cleaned up after 7 days.

---

## 🖥️ Dashboard Features

- **Live Camera Feed** — MJPEG stream with vehicle detection overlays
- **Per-Lane Metrics** — vehicle count, vehicles/min, density badge
- **Signal Status** — animated traffic light indicators
- **Mode Toggle** — switch between Automatic and Manual modes
- **Manual Override** — buttons to set individual lane lights (only in Manual mode)
- **Speed Violations** — table showing recent violations
- **All-Red Button** — emergency stop for all lanes

---

## 📜 License

MIT — free to use, modify, and share.

---

## 🙏 Credits

Built with: Flask · Picamera2 · OpenCV · RPi.GPIO · NumPy
