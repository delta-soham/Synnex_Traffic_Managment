# 🚦 SmartRail Traffic System

> Smart two-road railway crossing controller built on a **Raspberry Pi Zero 2W**.  
> Uses IR sensors to count vehicles and VL53L0X ToF sensors to measure speed.  
> Signals switch automatically after **N cars** pass, with a round-robin fallback when no cars are detected. A live camera feed is served over Wi-Fi.

---

## 📸 Features

| Feature | Details |
|---|---|
| Signal trigger | Switch after **N cars** counted by IR sensor |
| Round-robin fallback | Auto-switch after **30 s** if no cars on either road |
| Speed detection | VL53L0X ToF sensors calculate vehicle speed |
| Speed violation | Both lights → RED, railway gate closes, buzzer fires |
| Live camera | MJPEG stream served by Flask at `http://<PI_IP>:5000` |
| Dashboard | Real-time signal status, car count progress bar, speed, ToF distance |
| Auto-start | Systemd service starts on boot, restarts on crash |

---

## 🛒 Hardware Required

| Qty | Component |
|-----|-----------|
| 1 | Raspberry Pi Zero 2W |
| 1 | Pi Camera Module (v1.3 / v2 / HQ) |
| 2 | VL53L0X Time-of-Flight sensor (I²C) |
| 2 | IR obstacle sensor module (active LOW) |
| 6 | 5 mm LEDs — 2× Red, 2× Yellow, 2× Green |
| 6 | 220 Ω resistors (one per LED) |
| 1 | 5V relay module (for gate) |
| 1 | Active buzzer module |
| — | Jumper wires, breadboard / PCB |
| 1 | 5V / 2.5A USB-C power supply |

---

## 📌 Pin Reference

### Pi Zero 2W — Full 40-pin Header

```
                    3V3  (1) (2)  5V
          SDA / GPIO 2  (3) (4)  5V
          SCL / GPIO 3  (5) (6)  GND
                GPIO 4  (7) (8)  GPIO 14
                   GND  (9)(10)  GPIO 15
     IR Road-1 / GPIO17 (11)(12) GPIO 18
                GPIO 27 (13)(14) GND      ← IR Road-2
                GPIO 22 (15)(16) GPIO 23  ← ToF XSHUT-1
                   3V3 (17)(18) GPIO 24   ← ToF XSHUT-2
                GPIO 10 (19)(20) GND
                GPIO  9 (21)(22) GPIO 25
                GPIO 11 (23)(24) GPIO  8
                   GND (25)(26) GPIO  7
                GPIO  0 (27)(28) GPIO  1
  Road-1 RED  / GPIO 5  (29)(30) GND
  Road-1 YEL  / GPIO 6  (31)(32) GPIO 12
  Road-1 GRN  / GPIO13  (33)(34) GND
  Road-2 YEL  / GPIO19  (35)(36) GPIO 16  ← Buzzer
  Road-2 GRN  / GPIO26  (37)(38) GPIO 20  ← Gate relay
                   GND (39)(40) GPIO 21   ← Road-2 RED
```

> **Note:** Pin numbers in parentheses are **physical (board) numbers**.  
> The labels (GPIO N) are **BCM numbers** used in the code.

---

### Wiring Summary Table

| Signal | BCM GPIO | Physical Pin | Wire Colour (suggested) |
|--------|----------|-------------|------------------------|
| I²C SDA (ToF shared) | GPIO 2 | Pin 3 | Blue |
| I²C SCL (ToF shared) | GPIO 3 | Pin 5 | Yellow |
| IR Sensor — Road 1 | GPIO 17 | Pin 11 | White |
| IR Sensor — Road 2 | GPIO 27 | Pin 13 | White |
| ToF XSHUT — Sensor 1 | GPIO 23 | Pin 16 | Orange |
| ToF XSHUT — Sensor 2 | GPIO 24 | Pin 18 | Orange |
| Road 1 — RED LED | GPIO 5 | Pin 29 | Red |
| Road 1 — YELLOW LED | GPIO 6 | Pin 31 | Yellow |
| Road 1 — GREEN LED | GPIO 13 | Pin 33 | Green |
| Road 2 — RED LED | GPIO 19 | Pin 35 | Red |
| Road 2 — YELLOW LED | GPIO 26 | Pin 37 | Yellow |
| Road 2 — GREEN LED | GPIO 21 | Pin 40 | Green |
| Gate relay IN | GPIO 20 | Pin 38 | Purple |
| Buzzer (+) | GPIO 16 | Pin 36 | Grey |

All GND pins on the Pi can be used interchangeably.  
All VCC for sensors → **3.3 V** (Pin 1 or 17).  
LED cathodes (–) → GND via **220 Ω resistor**.

---

### VL53L0X Wiring (both sensors)

```
VL53L0X   →   Pi Zero 2W
─────────────────────────
VCC       →   3.3V (Pin 1)
GND       →   GND  (Pin 6)
SDA       →   GPIO 2 / Pin 3
SCL       →   GPIO 3 / Pin 5
XSHUT-1   →   GPIO 23 / Pin 16   (Sensor 1 only)
XSHUT-2   →   GPIO 24 / Pin 18   (Sensor 2 only)
```

> Both sensors share the same SDA/SCL lines.  
> The XSHUT pins allow the code to boot them one at a time and assign  
> unique I²C addresses: Sensor 1 → `0x29`, Sensor 2 → `0x30`.

---

### IR Sensor Wiring (both sensors)

```
IR Module   →   Pi Zero 2W
──────────────────────────
VCC         →   3.3V
GND         →   GND
OUT         →   GPIO 17 (Road 1) / GPIO 27 (Road 2)
```

> IR sensors must output **active LOW** (output goes LOW when beam is broken).  
> Internal pull-up resistors are enabled in software (`GPIO.PUD_UP`).

---

## 🧠 Signal Logic

```
Road 1 GREEN
     │
     ├─ IR counts N cars (phase_count >= CAR_TRIGGER_COUNT)
     │  AND at least MIN_GREEN_SEC has elapsed
     │                          → switch (car_count trigger)
     │
     ├─ Both roads idle AND ROUND_ROBIN_SEC elapsed
     │                          → switch (round-robin trigger)
     │
     ├─ MAX_GREEN_SEC elapsed   → switch (hard cap)
     │
     └─ ToF speed > limit       → BOTH RED + gate close (emergency)
          │
          └── auto-recover after 10 s
```

| Config constant | Default | Meaning |
|---|---|---|
| `CAR_TRIGGER_COUNT` | `5` | Cars on active road → switch |
| `MIN_GREEN_SEC` | `10` | Minimum green time before count-switch |
| `ROUND_ROBIN_SEC` | `30` | Idle timeout → round-robin switch |
| `MAX_GREEN_SEC` | `60` | Hard cap, prevents starvation |
| `SPEED_LIMIT_KMPH` | `40` | Speed violation threshold |

---

## 📁 File Structure

```
smartrail/
├── traffic_system.py    ← main application
├── install.sh           ← one-command Pi setup
├── requirements.txt     ← auto-generated after install
└── README.md            ← this file
```

---

## 🚀 Setup

### 1. Flash the Pi

Use **Raspberry Pi Imager** → Raspberry Pi OS Lite (64-bit).  
In the settings: enable SSH, set Wi-Fi SSID + password.

### 2. Transfer files

```bash
# From your PC
scp traffic_system.py install.sh pi@<PI_IP>:~/smartrail/
```

### 3. Run the installer

```bash
ssh pi@<PI_IP>
cd ~/smartrail
sudo bash install.sh
```

The installer will:
- Enable I²C and camera interfaces
- Install all system packages (`python3-picamera2`, `opencv`, etc.)
- Create a Python venv at `/home/pi/smartrail/venv/`
- Install `flask`, `RPi.GPIO`, `VL53L0X`, `smbus2` into the venv
- Register and start the `smartrail` systemd service

### 4. Open the dashboard

```
http://<PI_IP>:5000
```

---

## ⚙️ Service Commands

```bash
sudo systemctl status  smartrail      # check status
sudo systemctl restart smartrail      # restart
sudo systemctl stop    smartrail      # stop
sudo journalctl -u smartrail -f       # live log stream
```

### Manual run (for testing)

```bash
source /home/pi/smartrail/venv/bin/activate
python traffic_system.py
```

---

## 🌐 Web Endpoints

| URL | Description |
|-----|-------------|
| `http://<PI_IP>:5000/` | Live dashboard |
| `http://<PI_IP>:5000/stream` | Raw MJPEG stream |
| `http://<PI_IP>:5000/api/state` | JSON state (for integrations) |

---

## 🐍 Python Dependencies

| Package | Source | Why |
|---------|--------|-----|
| `picamera2` | apt (system) | Pi Camera — pre-built for ARM |
| `opencv-python` | apt (system) | Frame processing + timestamp overlay |
| `flask` | pip (venv) | Web server + MJPEG streaming |
| `RPi.GPIO` | pip (venv) | GPIO control for LEDs, relay, buzzer |
| `VL53L0X` | pip (venv) | ToF sensor I²C driver |
| `smbus2` | pip (venv) | I²C communication layer |

> The venv uses `--system-site-packages` so picamera2 and opencv  
> (which are very slow to build from source on Pi Zero 2W) are  
> reused from the system apt installation.

---

## 🔧 Customisation

All tunable values are at the top of `traffic_system.py` under `CONFIGURATION`:

```python
CAR_TRIGGER_COUNT = 5    # ← change this to require more/fewer cars
MIN_GREEN_SEC     = 10   # ← minimum hold before count-trigger fires
ROUND_ROBIN_SEC   = 30   # ← idle fallback timer
MAX_GREEN_SEC     = 60   # ← absolute maximum green time
SPEED_LIMIT_KMPH  = 40   # ← speed that triggers emergency
CAMERA_FPS        = 15   # ← lower this if Pi CPU is overloaded
```

---

## 📜 License

MIT — free to use, modify, and share.

---

## 🙏 Credits

Built with: Flask · Picamera2 · OpenCV · RPi.GPIO · VL53L0X Python library
# Synnex_Traffic_Managment
