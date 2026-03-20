#!/usr/bin/env python3
"""
SmartRail Traffic System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hardware : Raspberry Pi Zero 2W
Sensors  : 2× VL53L0X ToF (speed detection)
           2× IR sensor  (vehicle counting / trigger)
Lights   : 2× 3-LED traffic light (Red / Yellow / Green)
Camera   : Pi Camera Module (MJPEG live stream)

Signal Logic
━━━━━━━━━━━━
PRIMARY  — After CAR_TRIGGER_COUNT cars pass the active IR → switch signal
FALLBACK — If no cars on EITHER road for ROUND_ROBIN_SEC → switch anyway
EMERGENCY— Speed > SPEED_LIMIT_KMPH → both roads RED for 10 s

GPIO (BCM) pin map  ← physical pin numbers in README
━━━━━━━━━━━━━━━━━━
IR  Road-1  → GPIO 17        IR  Road-2  → GPIO 27
ToF XSHUT-1 → GPIO 23        ToF XSHUT-2 → GPIO 24
ToF SDA     → GPIO 2 (I²C)   ToF SCL     → GPIO 3 (I²C)
Road-1 RED  → GPIO 5         Road-2 RED  → GPIO 19
Road-1 YEL  → GPIO 6         Road-2 YEL  → GPIO 26
Road-1 GRN  → GPIO 13        Road-2 GRN  → GPIO 21
"""

import time
import threading
import logging
import socket
import datetime
import sys
import copy

import RPi.GPIO as GPIO

try:
    import VL53L0X
    TOF_AVAILABLE = True
except ImportError:
    TOF_AVAILABLE = False

try:
    from picamera2 import Picamera2
    import cv2
    CAM_AVAILABLE = True
except ImportError:
    CAM_AVAILABLE = False

from flask import Flask, Response, render_template_string, jsonify

# ══════════════════════════════════════════════
#  CONFIGURATION  ← change these to tune behaviour
# ══════════════════════════════════════════════

HOST          = "0.0.0.0"
PORT          = 5000

# Camera
RESOLUTION    = (640, 480)
JPEG_QUALITY  = 70
CAMERA_FPS    = 15

# GPIO pins (BCM numbering — see README for physical pin numbers)
IR1_PIN       = 17
IR2_PIN       = 27
TOF_XSHUT1    = 23
TOF_XSHUT2    = 24
ROAD1_RED     = 5
ROAD1_YELLOW  = 6
ROAD1_GREEN   = 13
ROAD2_RED     = 19
ROAD2_YELLOW  = 26
ROAD2_GREEN   = 21

# ── Signal trigger ────────────────────────────
CAR_TRIGGER_COUNT = 5    # cars on the GREEN road → switch signal
MIN_GREEN_SEC     = 10   # green must hold at least this long before count-switch allowed
ROUND_ROBIN_SEC   = 30   # if BOTH roads idle → auto-switch after this many seconds
MAX_GREEN_SEC     = 60   # hard cap — switch even if cars keep coming

YELLOW_BLINK_TIMES = 3
YELLOW_BLINK_INTV  = 0.4

# ── Safety ────────────────────────────────────
SPEED_LIMIT_KMPH  = 40
TOF_RANGE_CM      = 200
SPEED_SAMPLE_SEC  = 0.5
IR_DEBOUNCE_MS    = 50

# ══════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/smartrail.log")
    ]
)
log = logging.getLogger("SmartRail")

# ══════════════════════════════════════════════
#  GPIO SETUP
# ══════════════════════════════════════════════
def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(IR1_PIN,    GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(IR2_PIN,    GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(TOF_XSHUT1, GPIO.OUT)
    GPIO.setup(TOF_XSHUT2, GPIO.OUT)
    for p in [ROAD1_RED, ROAD1_YELLOW, ROAD1_GREEN,
              ROAD2_RED, ROAD2_YELLOW, ROAD2_GREEN,
              ]:
        GPIO.setup(p, GPIO.OUT)
        GPIO.output(p, GPIO.LOW)
    log.info("GPIO ready")

# ══════════════════════════════════════════════
#  TRAFFIC LIGHT
# ══════════════════════════════════════════════
class TrafficLight:
    _MAP = {"red":(1,0,0), "yellow":(0,1,0), "green":(0,0,1), "off":(0,0,0)}

    def __init__(self, road_id, r, y, g):
        self.road_id = road_id
        self._pins   = (r, y, g)
        self.state   = "off"
        self._lock   = threading.Lock()
        self.set("red")

    def set(self, color):
        with self._lock:
            for pin, val in zip(self._pins, self._MAP.get(color, (1,0,0))):
                GPIO.output(pin, val)
            self.state = color
            log.info(f"  Light Road-{self.road_id} → {color.upper()}")

    def blink_yellow(self, times=YELLOW_BLINK_TIMES, intv=YELLOW_BLINK_INTV):
        for _ in range(times):
            self.set("yellow"); time.sleep(intv)
            self.set("off");    time.sleep(intv)

# ══════════════════════════════════════════════
#  IR COUNTER
# ══════════════════════════════════════════════
class IRCounter:
    """
    Counts vehicles via interrupt on FALLING edge (IR beam break).
    `phase_count`  — resets to 0 every time this road gets a green phase.
                     The controller uses this to decide when N cars have passed.
    `total`        — lifetime counter, never reset.
    `per_min`      — rolling 60-second window count.
    """
    def __init__(self, road_id, pin):
        self.road_id     = road_id
        self.total       = 0
        self.phase_count = 0
        self.per_min     = 0
        self._times      = []
        self._last_trig  = 0.0
        GPIO.add_event_detect(pin, GPIO.FALLING,
                              callback=self._detect,
                              bouncetime=IR_DEBOUNCE_MS)

    def _detect(self, _ch):
        now = time.time()
        if now - self._last_trig < 0.1:
            return
        self._last_trig   = now
        self.total       += 1
        self.phase_count += 1
        self._times.append(now)
        self._times  = [t for t in self._times if now - t <= 60]
        self.per_min = len(self._times)
        log.info(f"  IR Road-{self.road_id}: phase={self.phase_count} "
                 f"total={self.total}  {self.per_min}/min")

    def reset_phase(self):
        self.phase_count = 0

# ══════════════════════════════════════════════
#  TOF SPEED SENSOR
# ══════════════════════════════════════════════
class ToFSensor:
    def __init__(self, sensor_id, i2c_addr):
        self.sensor_id   = sensor_id
        self.i2c_addr    = i2c_addr
        self._tof        = None
        self._prev_dist  = None
        self._prev_time  = None
        self.speed_kmph  = 0.0
        self.distance_cm = -1.0
        self._lock       = threading.Lock()

    def begin(self):
        if not TOF_AVAILABLE:
            log.warning(f"ToF-{self.sensor_id}: VL53L0X lib missing"); return False
        try:
            self._tof = VL53L0X.VL53L0X(i2c_address=self.i2c_addr)
            self._tof.open()
            self._tof.start_ranging(VL53L0X.VL53L0X_BETTER_ACCURACY_MODE)
            log.info(f"ToF-{self.sensor_id} ready @ 0x{self.i2c_addr:02X}")
            return True
        except Exception as e:
            log.error(f"ToF-{self.sensor_id} init: {e}"); return False

    def update(self):
        if not self._tof: return
        with self._lock:
            now = time.time()
            try:
                mm = self._tof.get_distance()
                dist = mm / 10.0 if mm and mm > 0 else -1.0
            except Exception:
                dist = -1.0
            self.distance_cm = dist
            if dist > 0 and self._prev_dist is not None:
                dt = now - self._prev_time
                if 0 < dt <= 2.0:
                    raw = (abs(self._prev_dist - dist) / 100.0 / dt) * 3.6
                    if 0 < raw < 200:
                        self.speed_kmph = round(raw, 1)
            if dist > 0:
                self._prev_dist = dist
                self._prev_time = now

    @property
    def vehicle_present(self):
        return 0 < self.distance_cm < TOF_RANGE_CM

    def stop(self):
        try: self._tof.stop_ranging(); self._tof.close()
        except Exception: pass


def init_tof_pair():
    """
    Boot sensors one at a time via XSHUT so they get
    unique I²C addresses: sensor-1 stays 0x29, sensor-2 → 0x30.
    """
    GPIO.output(TOF_XSHUT1, GPIO.LOW)
    GPIO.output(TOF_XSHUT2, GPIO.LOW)
    time.sleep(0.1)

    GPIO.output(TOF_XSHUT1, GPIO.HIGH); time.sleep(0.15)
    tof1 = ToFSensor(1, 0x29); tof1.begin()

    GPIO.output(TOF_XSHUT2, GPIO.HIGH); time.sleep(0.15)
    tof2 = ToFSensor(2, 0x30); tof2.begin()

    return tof1, tof2

# ══════════════════════════════════════════════
#  CAMERA STREAMER
# ══════════════════════════════════════════════
class CameraStreamer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._frame   = None
        self._lock    = threading.Lock()
        self._running = True

    def run(self):
        if not CAM_AVAILABLE:
            log.warning("picamera2/cv2 not found — camera disabled")
            self._placeholder(); return

        cam = Picamera2()
        cam.configure(cam.create_video_configuration(
            main={"size": RESOLUTION, "format": "RGB888"},
            controls={"FrameRate": CAMERA_FPS}))
        cam.start()
        log.info(f"Camera {RESOLUTION} @ {CAMERA_FPS}fps")

        inv = 1.0 / CAMERA_FPS
        while self._running:
            try:
                t0    = time.time()
                frame = cam.capture_array()
                ts    = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
                for col, thick in [((0,0,0),2), ((0,255,120),1)]:
                    cv2.putText(frame, ts, (9,23),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.52, col, thick, cv2.LINE_AA)
                for col, thick in [((0,0,180),2), ((60,120,255),1)]:
                    cv2.putText(frame, "● LIVE", (RESOLUTION[0]-90,23),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.52, col, thick, cv2.LINE_AA)
                _, buf = cv2.imencode(".jpg", frame,
                                      [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                with self._lock:
                    self._frame = buf.tobytes()
                time.sleep(max(0, inv - (time.time()-t0)))
            except Exception as e:
                log.error(f"Camera: {e}"); time.sleep(0.5)
        cam.stop()

    def _placeholder(self):
        grey = (b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
                b'\xff\xdb\x00C\x00'+bytes([8]*64)+
                b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
                b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01'
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06'
                b'\x07\x08\x09\x0a\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x00\xff\xd9')
        with self._lock: self._frame = grey
        while self._running: time.sleep(1)

    def get_frame(self):
        with self._lock: return self._frame

    def stop(self): self._running = False

# ══════════════════════════════════════════════
#  MJPEG
# ══════════════════════════════════════════════
def mjpeg(cam):
    while True:
        f = cam.get_frame()
        if f:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + f + b"\r\n"
        time.sleep(1.0 / CAMERA_FPS)

# ══════════════════════════════════════════════
#  SHARED STATE
# ══════════════════════════════════════════════
state = {
    "road1": {"signal":"red","speed":0.0,"distance":0.0,
              "count":0,"phase_count":0,"per_min":0,"vehicle":False},
    "road2": {"signal":"red","speed":0.0,"distance":0.0,
              "count":0,"phase_count":0,"per_min":0,"vehicle":False},
    "alert":      "",
    "phase":      "road1_green",
    "trigger":    "—",
    "car_target": CAR_TRIGGER_COUNT,
    "rr_timeout": ROUND_ROBIN_SEC,
}
_slock = threading.Lock()

def ust(**kw):
    with _slock:
        for k, v in kw.items():
            if isinstance(v, dict) and isinstance(state.get(k), dict):
                state[k].update(v)
            else:
                state[k] = v

# ══════════════════════════════════════════════
#  TRAFFIC CONTROLLER
# ══════════════════════════════════════════════
class TrafficController(threading.Thread):
    """
    Two-road signal controller.

    Switch conditions (checked every SPEED_SAMPLE_SEC inside the green phase):
      1. CAR_TRIGGER_COUNT cars have passed the IR on the active road
         AND MIN_GREEN_SEC has elapsed          → "car_count"  trigger
      2. BOTH roads have seen zero cars AND
         ROUND_ROBIN_SEC has elapsed            → "round_robin" trigger
      3. MAX_GREEN_SEC elapsed regardless       → "max hold"   trigger
      4. Speed violation on either ToF          → emergency red
    """

    def __init__(self, l1, l2, ir1, ir2, tof1, tof2):
        super().__init__(daemon=True)
        self.l1  = l1;  self.l2  = l2
        self.ir1 = ir1; self.ir2 = ir2
        self.tof1= tof1;self.tof2= tof2
        self._running     = True
        self._emergency   = False

    # ─── helpers ─────────────────────────────


    def _poll(self):
        """Update sensor readings. Returns True on speed violation."""
        self.tof1.update(); self.tof2.update()
        viol = False
        for rid, tof, ir in [(1,self.tof1,self.ir1),(2,self.tof2,self.ir2)]:
            ust(**{f"road{rid}": {
                "speed":       tof.speed_kmph,
                "distance":    round(tof.distance_cm, 1),
                "vehicle":     tof.vehicle_present,
                "count":       ir.total,
                "phase_count": ir.phase_count,
                "per_min":     ir.per_min,
            }})
            if tof.speed_kmph > SPEED_LIMIT_KMPH:
                self._emergency = True
                ust(alert=f"Speed {tof.speed_kmph:.0f} km/h on Road {rid}!")
                log.warning(f"SPEED VIOLATION Road {rid}: {tof.speed_kmph:.0f} km/h")
                viol = True
        return viol

    def _emergency_red(self, hold=10.0):
        self.l1.set("red"); self.l2.set("red")
        ust(road1={"signal":"red"}, road2={"signal":"red"},
            phase="emergency", trigger="speed violation")
        log.warning(f"EMERGENCY RED — {hold}s")
        t = time.time()
        while time.time() - t < hold:
            self._poll(); time.sleep(SPEED_SAMPLE_SEC)
        self._emergency = False

    def _transition(self, outgoing):
        outgoing.blink_yellow()
        outgoing.set("red")
        ust(**{f"road{outgoing.road_id}": {"signal":"red"}, "phase":"transition"})
        time.sleep(1.0)   # brief all-red gap

    # ─── green phase ─────────────────────────
    def _green_phase(self, active_light, active_ir, other_light):
        """
        Keep active road GREEN until a switch condition fires.
        Returns: 'car_count' | 'round_robin' | 'max_hold' | 'emergency' | 'stopped'
        """
        rid = active_light.road_id

        # Activate
        active_light.set("green")
        other_light.set("red")
        active_ir.reset_phase()
        ust(**{f"road{rid}":                 {"signal":"green"},
               f"road{other_light.road_id}": {"signal":"red"},
               "phase":   f"road{rid}_green",
               "trigger": "—"})

        log.info(f"Road-{rid} GREEN | switch on {CAR_TRIGGER_COUNT} cars "
                 f"or {ROUND_ROBIN_SEC}s idle round-robin")

        phase_start = time.time()

        while self._running:
            if self._poll():
                return "emergency"

            elapsed = time.time() - phase_start

            # ── PRIMARY: car-count trigger ────────────────────────────
            if (active_ir.phase_count >= CAR_TRIGGER_COUNT
                    and elapsed >= MIN_GREEN_SEC):
                log.info(f"Road-{rid}: {active_ir.phase_count} cars → switch "
                         f"(elapsed {elapsed:.1f}s)")
                ust(trigger=f"{active_ir.phase_count} cars counted on Road {rid}")
                return "car_count"

            # ── FALLBACK: round-robin — both roads idle ───────────────
            both_idle = (self.ir1.phase_count == 0 and self.ir2.phase_count == 0)
            if both_idle and elapsed >= ROUND_ROBIN_SEC:
                log.info(f"Road-{rid}: no traffic anywhere → round-robin "
                         f"after {elapsed:.1f}s")
                ust(trigger="round-robin (no vehicles detected)")
                return "round_robin"

            # ── SAFETY CAP: max hold time ─────────────────────────────
            if elapsed >= MAX_GREEN_SEC:
                log.info(f"Road-{rid}: max hold {MAX_GREEN_SEC}s → forced switch")
                ust(trigger=f"max hold {MAX_GREEN_SEC}s reached")
                return "max_hold"

            time.sleep(SPEED_SAMPLE_SEC)

        return "stopped"

    # ─── main loop ───────────────────────────
    def run(self):
        log.info("Controller running")
        roads = [(self.l1, self.ir1, self.l2),
                 (self.l2, self.ir2, self.l1)]
        idx = 0

        while self._running:
            if self._emergency:
                self._emergency_red(10); continue

            al, air, ol = roads[idx]
            reason = self._green_phase(al, air, ol)

            if reason == "emergency":
                self._emergency_red(10)
            else:
                self._transition(al)

            idx = 1 - idx   # alternate roads

    def stop(self): self._running = False

# ══════════════════════════════════════════════
#  FLASK
# ══════════════════════════════════════════════
app  = Flask(__name__)
_cam = None

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>SmartRail — Traffic Control</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Space+Mono:wght@400;700&display=swap');
:root{--bg:#070a0e;--surf:#0d1117;--card:#111820;--border:#1b2535;
  --accent:#00e5ff;--accent2:#ff6b35;--green:#00ff88;
  --red:#ff3355;--yellow:#ffd700;--txt:#dce8f0;--muted:#4a5a6a}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font-family:'Syne',sans-serif;min-height:100vh}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(rgba(0,229,255,.025) 1px,transparent 1px),
  linear-gradient(90deg,rgba(0,229,255,.025) 1px,transparent 1px);background-size:44px 44px}
nav{position:sticky;top:0;z-index:50;display:flex;align-items:center;
  justify-content:space-between;padding:14px 28px;
  background:rgba(7,10,14,.93);border-bottom:1px solid var(--border);backdrop-filter:blur(10px)}
.brand{font-size:19px;font-weight:800;letter-spacing:-.5px}
.brand em{color:var(--accent);font-style:normal}
.live-badge{display:flex;align-items:center;gap:7px;font-family:'Space Mono',monospace;
  font-size:12px;color:var(--green);background:#0a1a12;border:1px solid #0d2a1a;
  padding:5px 14px;border-radius:20px}
.pulse{width:8px;height:8px;border-radius:50%;background:var(--green);
  box-shadow:0 0 6px var(--green);animation:blink 1.8s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.grid{position:relative;z-index:1;display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:22px 28px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;transition:border-color .2s}
.card:hover{border-color:rgba(0,229,255,.15)}
.ctitle{font-size:10px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;
  color:var(--muted);margin-bottom:18px;display:flex;align-items:center;gap:7px}
.ctdot{width:5px;height:5px;border-radius:50%;background:var(--accent)}
.sig-card{position:relative;overflow:hidden}
.sig-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:linear-gradient(90deg,var(--accent),transparent)}
.sig-card.r2::before{background:linear-gradient(90deg,var(--accent2),transparent)}
.sig-body{display:flex;align-items:center;gap:18px;margin-bottom:16px}
.lights{display:flex;flex-direction:column;gap:7px}
.bulb{width:24px;height:24px;border-radius:50%;background:var(--border);transition:background .35s,box-shadow .35s}
.bulb.on-red{background:var(--red);box-shadow:0 0 16px var(--red)}
.bulb.on-yellow{background:var(--yellow);box-shadow:0 0 16px var(--yellow)}
.bulb.on-green{background:var(--green);box-shadow:0 0 16px var(--green)}
.road-label{font-size:34px;font-weight:800;letter-spacing:-2px;line-height:1}
.sig-pill{display:inline-block;font-family:'Space Mono',monospace;font-size:12px;
  padding:3px 10px;border-radius:6px;margin-top:5px}
.sig-pill.red{background:rgba(255,51,85,.15);color:var(--red)}
.sig-pill.yellow{background:rgba(255,215,0,.15);color:var(--yellow)}
.sig-pill.green{background:rgba(0,255,136,.15);color:var(--green)}
.prog-wrap{margin-top:12px}
.prog-label{font-size:11px;color:var(--muted);margin-bottom:5px;display:flex;justify-content:space-between}
.prog-bar{height:6px;background:var(--border);border-radius:3px;overflow:hidden}
.prog-fill{height:100%;background:var(--accent);border-radius:3px;transition:width .4s;width:0%}
.prog-fill.full{background:var(--green)}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.met{background:var(--surf);border-radius:10px;padding:12px 14px}
.met-val{font-family:'Space Mono',monospace;font-size:22px;font-weight:700;line-height:1}
.met-val.safe{color:var(--green)}.met-val.warn{color:var(--yellow)}.met-val.bad{color:var(--red)}
.met-lbl{font-size:10px;color:var(--muted);margin-top:4px;letter-spacing:.5px}
.info-row{grid-column:1/3;background:var(--surf);border:1px solid var(--border);
  border-radius:12px;padding:14px 18px;display:flex;align-items:center;gap:18px;flex-wrap:wrap;font-size:13px}
.info-lbl{color:var(--muted);font-size:10px;letter-spacing:1.5px;text-transform:uppercase;white-space:nowrap}
.info-val{font-family:'Space Mono',monospace;color:var(--accent)}
.alert-banner{grid-column:1/3;padding:12px 20px;border-radius:12px;
  background:rgba(255,51,85,.12);border:1px solid var(--red);
  color:var(--red);font-size:14px;font-weight:700;align-items:center;gap:10px;display:none}
.cam-card{grid-column:1/3}
.cam-wrap{position:relative;border-radius:12px;overflow:hidden;background:#000;border:1px solid var(--border)}
.cam-wrap img{width:100%;display:block}
.cam-tag{position:absolute;top:10px;left:10px;display:flex;align-items:center;gap:6px;
  background:rgba(0,0,0,.65);padding:4px 10px;border-radius:6px;font-family:'Space Mono',monospace;font-size:10px}
.cam-offline{display:none;padding:60px;text-align:center;color:var(--muted);font-size:14px}
@media(max-width:680px){.grid{grid-template-columns:1fr;padding:14px}
  .cam-card,.alert-banner,.info-row{grid-column:1}}
</style>
</head>
<body>
<nav>
  <div class="brand">🚦 Smart<em>Rail</em></div>
  <div class="live-badge"><div class="pulse"></div>LIVE</div>
  <div style="font-family:'Space Mono',monospace;font-size:11px;color:var(--muted)" id="clk"></div>
</nav>
<div class="grid">
  <div class="alert-banner" id="alert-bar"><span>⚠</span><span id="alert-txt"></span></div>


  <!-- trigger info -->
  <div class="info-row">
    <div><div class="info-lbl">Trigger Mode</div>
      <div class="info-val">Every <span id="car-target">?</span> cars&nbsp;&nbsp;|&nbsp;&nbsp;Round-robin after <span id="rr-t">?</span>s idle</div></div>
    <div style="margin-left:auto">
      <div class="info-lbl">Last Switch</div>
      <div class="info-val" id="trigger-val">—</div>
    </div>
  </div>

  <!-- Road 1 -->
  <div class="card sig-card">
    <div class="ctitle"><span class="ctdot"></span>ROAD 1 — NORTH</div>
    <div class="sig-body">
      <div class="lights">
        <div class="bulb" id="r1-red"></div>
        <div class="bulb" id="r1-yellow"></div>
        <div class="bulb" id="r1-green"></div>
      </div>
      <div><div class="road-label">ROAD 1</div><span class="sig-pill red" id="r1-pill">RED</span></div>
    </div>
    <div class="prog-wrap">
      <div class="prog-label"><span>Cars this phase</span>
        <span><span id="r1-pc">0</span> / <span id="r1-tgt">?</span></span></div>
      <div class="prog-bar"><div class="prog-fill" id="r1-prog"></div></div>
    </div>
    <div class="metrics">
      <div class="met"><div class="met-val safe" id="r1-spd">0.0</div><div class="met-lbl">SPEED km/h</div></div>
      <div class="met"><div class="met-val" id="r1-cnt">0</div><div class="met-lbl">TOTAL VEHICLES</div></div>
      <div class="met"><div class="met-val" id="r1-vpm">0</div><div class="met-lbl">VEHICLES/MIN</div></div>
      <div class="met"><div class="met-val" id="r1-dst">—</div><div class="met-lbl">TOF DIST cm</div></div>
    </div>
  </div>

  <!-- Road 2 -->
  <div class="card sig-card r2">
    <div class="ctitle"><span class="ctdot" style="background:var(--accent2)"></span>ROAD 2 — SOUTH</div>
    <div class="sig-body">
      <div class="lights">
        <div class="bulb" id="r2-red"></div>
        <div class="bulb" id="r2-yellow"></div>
        <div class="bulb" id="r2-green"></div>
      </div>
      <div><div class="road-label">ROAD 2</div><span class="sig-pill red" id="r2-pill">RED</span></div>
    </div>
    <div class="prog-wrap">
      <div class="prog-label"><span>Cars this phase</span>
        <span><span id="r2-pc">0</span> / <span id="r2-tgt">?</span></span></div>
      <div class="prog-bar"><div class="prog-fill" id="r2-prog"></div></div>
    </div>
    <div class="metrics">
      <div class="met"><div class="met-val safe" id="r2-spd">0.0</div><div class="met-lbl">SPEED km/h</div></div>
      <div class="met"><div class="met-val" id="r2-cnt">0</div><div class="met-lbl">TOTAL VEHICLES</div></div>
      <div class="met"><div class="met-val" id="r2-vpm">0</div><div class="met-lbl">VEHICLES/MIN</div></div>
      <div class="met"><div class="met-val" id="r2-dst">—</div><div class="met-lbl">TOF DIST cm</div></div>
    </div>
  </div>

  <!-- Camera -->
  <div class="card cam-card">
    <div class="ctitle"><span class="ctdot"></span>LIVE CAMERA FEED</div>
    <div class="cam-wrap">
      <img id="cam" src="/stream" alt="Live" onerror="camErr()" onload="camOk()"/>
      <div class="cam-tag"><div class="pulse"></div><span>LIVE · ROAD CAM</span></div>
      <div class="cam-offline" id="cam-offline">📷 Camera offline</div>
    </div>
  </div>
</div>

<script>
setInterval(()=>{document.getElementById('clk').textContent=new Date().toLocaleTimeString();},1000);
function camOk(){document.getElementById('cam').style.display='block';document.getElementById('cam-offline').style.display='none';}
function camErr(){document.getElementById('cam').style.display='none';document.getElementById('cam-offline').style.display='block';
  setTimeout(()=>{document.getElementById('cam').src='/stream?t='+Date.now();},3000);}
function setLight(n,c){
  ['red','yellow','green'].forEach(x=>{document.getElementById(`r${n}-${x}`).className='bulb'+(x===c?` on-${x}`:'');});
  const p=document.getElementById(`r${n}-pill`);p.textContent=c.toUpperCase();p.className=`sig-pill ${c}`;}
function spdCls(v){return v>40?'bad':v>25?'warn':'safe';}
function setBar(n,count,target){
  const pct=Math.min(100,(count/target)*100);
  const b=document.getElementById(`r${n}-prog`);
  b.style.width=pct+'%';b.className='prog-fill'+(pct>=100?' full':'');
  document.getElementById(`r${n}-pc`).textContent=count;
  document.getElementById(`r${n}-tgt`).textContent=target;}
function poll(){
  fetch('/api/state').then(r=>r.json()).then(d=>{
    document.getElementById('car-target').textContent=d.car_target;
    document.getElementById('rr-t').textContent=d.rr_timeout;
    document.getElementById('trigger-val').textContent=d.trigger||'—';
    [1,2].forEach(n=>{
      const r=d[`road${n}`];
      setLight(n,r.signal);
      const sv=document.getElementById(`r${n}-spd`);
      sv.textContent=r.speed.toFixed(1);sv.className='met-val '+spdCls(r.speed);
      document.getElementById(`r${n}-cnt`).textContent=r.count;
      document.getElementById(`r${n}-vpm`).textContent=r.per_min;
      document.getElementById(`r${n}-dst`).textContent=r.distance>0?r.distance.toFixed(0):'—';
      setBar(n,r.phase_count,d.car_target);});
    const ab=document.getElementById('alert-bar');
    if(d.alert){ab.style.display='flex';document.getElementById('alert-txt').textContent=d.alert;}
    else{ab.style.display='none';}
  }).catch(()=>{});}
poll();setInterval(poll,800);
</script>
</body>
</html>"""

@app.route("/")
def index(): return render_template_string(PAGE)

@app.route("/stream")
def stream():
    return Response(mjpeg(_cam), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/state")
def api_state():
    with _slock: return jsonify(copy.deepcopy(state))

# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════
def get_ip():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80));ip=s.getsockname()[0];s.close();return ip
    except Exception: return "localhost"

def main():
    global _cam
    setup_gpio()

    tof1, tof2 = init_tof_pair()
    ir1  = IRCounter(1, IR1_PIN)
    ir2  = IRCounter(2, IR2_PIN)
    l1   = TrafficLight(1, ROAD1_RED,  ROAD1_YELLOW,  ROAD1_GREEN)
    l2   = TrafficLight(2, ROAD2_RED,  ROAD2_YELLOW,  ROAD2_GREEN)
    _cam = CameraStreamer(); _cam.start()
    ctrl = TrafficController(l1, l2, ir1, ir2, tof1, tof2); ctrl.start()

    ip = get_ip()
    print(f"\n{'━'*48}")
    print(f"  SmartRail Traffic System — ONLINE")
    print(f"{'━'*48}")
    print(f"  Dashboard : http://{ip}:{PORT}")
    print(f"  Stream    : http://{ip}:{PORT}/stream")
    print(f"  API state : http://{ip}:{PORT}/api/state")
    print(f"  Trigger   : {CAR_TRIGGER_COUNT} cars  |  round-robin {ROUND_ROBIN_SEC}s  |  hard cap {MAX_GREEN_SEC}s")
    print(f"{'━'*48}\n")

    try:
        app.run(host=HOST, port=PORT, threaded=True, debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down…")
        ctrl.stop(); _cam.stop()
        tof1.stop(); tof2.stop()
        l1.set("red"); l2.set("red")
        GPIO.cleanup()
        log.info("Done.")

if __name__ == "__main__":
    main()