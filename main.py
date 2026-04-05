#!/usr/bin/env python3
"""
main.py — Synnex Smart Traffic Management System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entry point for the complete system.

Hardware : Raspberry Pi Zero 2W
Input    : Camera Module (OpenCV-based vehicle detection)
Output   : Traffic Light LEDs via GPIO
Dashboard: Flask web server

Modules:
  camera.py             – video capture & vehicle detection
  traffic_controller.py – round-robin signal scheduling
  gpio_control.py       – LED traffic light control
  speed_detection.py    – camera-based speed estimation
  dashboard.py          – Flask web dashboard
  data_logger.py        – SQLite data persistence

Usage:
    python main.py              # run with defaults
    python main.py --port 8080  # custom port
    python main.py --no-speed   # disable speed detection (saves CPU)
"""

import sys
import time
import socket
import signal
import logging
import argparse
import threading

# ── Module imports ───────────────────────────────────────
from camera import VehicleDetector, CameraStreamer
from traffic_controller import TrafficController
from gpio_control import (
    TrafficLight, setup_gpio, cleanup_gpio, get_pin_info
)
from speed_detection import SpeedDetector
from data_logger import DataLogger
import dashboard

# ══════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════
HOST = "0.0.0.0"
PORT = 5000
LOG_INTERVAL = 30       # seconds between periodic data logging

# ══════════════════════════════════════════════════════════
#  LOGGING SETUP
# ══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("synnex_traffic.log", mode="a"),
    ]
)
log = logging.getLogger("Synnex.Main")


# ══════════════════════════════════════════════════════════
#  PERIODIC DATA LOGGER
# ══════════════════════════════════════════════════════════
class PeriodicLogger(threading.Thread):
    """
    Background thread that periodically logs vehicle counts
    and density readings to the database.
    """

    def __init__(self, detector: VehicleDetector,
                 data_logger: DataLogger,
                 interval: int = LOG_INTERVAL):
        super().__init__(daemon=True, name="PeriodicLogger")
        self.detector = detector
        self.data_logger = data_logger
        self.interval = interval
        self._running = True

    def run(self):
        log.info(f"Periodic logger started (every {self.interval}s)")
        while self._running:
            time.sleep(self.interval)
            try:
                for lane_id in [1, 2]:
                    data = self.detector.get_lane_data(lane_id)
                    self.data_logger.log_vehicle_count(
                        lane_id,
                        data["count"],
                        data["per_min"],
                        data["density"],
                    )
                    self.data_logger.log_density(
                        lane_id,
                        data["density"],
                        data["count"],
                    )
            except Exception as e:
                log.error(f"Periodic log error: {e}")

    def stop(self):
        self._running = False


# ══════════════════════════════════════════════════════════
#  UTILITIES
# ══════════════════════════════════════════════════════════
def get_local_ip():
    """Detect the Pi's local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Synnex Smart Traffic Management System"
    )
    parser.add_argument(
        "--port", type=int, default=PORT,
        help=f"Web dashboard port (default: {PORT})"
    )
    parser.add_argument(
        "--host", type=str, default=HOST,
        help=f"Bind address (default: {HOST})"
    )
    parser.add_argument(
        "--no-speed", action="store_true",
        help="Disable speed detection (saves CPU on Pi Zero 2W)"
    )
    parser.add_argument(
        "--log-interval", type=int, default=LOG_INTERVAL,
        help=f"Seconds between data log snapshots (default: {LOG_INTERVAL})"
    )
    return parser.parse_args()


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════
def main():
    args = parse_args()
    running = True

    # ── Banner ────────────────────────────────────────────
    print(f"\n{'━' * 52}")
    print(f"  🚦 Synnex Smart Traffic Management System")
    print(f"{'━' * 52}")
    print(f"  Starting up...")
    print(f"{'━' * 52}\n")

    # ── 1. GPIO Setup ────────────────────────────────────
    setup_gpio()

    # ── 2. Create traffic lights ─────────────────────────
    light1 = TrafficLight(lane_id=1)
    light2 = TrafficLight(lane_id=2)
    lights = {1: light1, 2: light2}
    log.info("Traffic lights initialised (both RED)")

    # ── 3. Create vehicle detector ───────────────────────
    detector = VehicleDetector()
    log.info("Vehicle detector ready")

    # ── 4. Start camera ──────────────────────────────────
    cam = CameraStreamer(detector)
    cam.start()
    log.info("Camera thread started")

    # ── 5. Create data logger ────────────────────────────
    data_log = DataLogger()

    # ── 6. Start traffic controller ──────────────────────
    controller = TrafficController(lights, detector)
    controller.start()
    log.info("Traffic controller started (AUTOMATIC mode)")

    # ── 7. Start speed detector (optional) ───────────────
    speed = None
    if not args.no_speed:
        speed = SpeedDetector(cam, data_log)
        speed.start()
        log.info("Speed detector started")
    else:
        # Create a dummy speed detector for the API
        speed = SpeedDetector(cam, data_log)
        log.info("Speed detection DISABLED (--no-speed)")

    # ── 8. Start periodic logger ─────────────────────────
    periodic = PeriodicLogger(detector, data_log, args.log_interval)
    periodic.start()

    # ── 9. Wire up Flask dashboard ───────────────────────
    dashboard.camera     = cam
    dashboard.detector   = detector
    dashboard.controller = controller
    dashboard.speed_det  = speed
    dashboard.data_logger = data_log

    # ── 10. Print status ─────────────────────────────────
    ip = get_local_ip()
    pin_info = get_pin_info()

    print(f"\n{'━' * 52}")
    print(f"  🚦 Synnex — ONLINE")
    print(f"{'━' * 52}")
    print(f"  Dashboard  : http://{ip}:{args.port}")
    print(f"  Stream     : http://{ip}:{args.port}/stream")
    print(f"  API State  : http://{ip}:{args.port}/api/state")
    print(f"  Speed Det  : {'ENABLED' if not args.no_speed else 'DISABLED'}")
    print(f"  Log to DB  : every {args.log_interval}s")
    print(f"{'─' * 52}")
    print(f"  GPIO Pin Mapping:")
    for lane_name, pins in pin_info.items():
        print(f"    {lane_name}:")
        for color, info in pins.items():
            print(f"      {color:>6s} → BCM {info['bcm_pin']:>2d}  "
                  f"(Physical Pin {info['physical_pin']})")
    print(f"{'━' * 52}\n")

    # ── Graceful shutdown handler ────────────────────────
    def shutdown(signum=None, frame=None):
        nonlocal running
        if not running:
            return
        running = False
        print(f"\n{'━' * 52}")
        print(f"  Shutting down...")
        print(f"{'━' * 52}")

        controller.stop()
        if speed:
            speed.stop()
        cam.stop()
        periodic.stop()

        # Set all lights to RED for safety
        light1.set("red")
        light2.set("red")

        cleanup_gpio()
        log.info("Shutdown complete.")
        print(f"  ✓ Shutdown complete\n{'━' * 52}\n")

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ── Start Flask ──────────────────────────────────────
    try:
        dashboard.app.run(
            host=args.host,
            port=args.port,
            threaded=True,
            debug=False,
            use_reloader=False,     # important: don't double-start threads
        )
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()
