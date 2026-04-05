#!/usr/bin/env python3
"""
gpio_control.py — GPIO Abstraction for Traffic Lights
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Clean abstraction layer for controlling traffic light LEDs
via Raspberry Pi GPIO pins. Falls back to console simulation
when RPi.GPIO is not available (for development / testing).

GPIO Pin Mapping (BCM numbering):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Lane 1: RED=5,  YELLOW=6,  GREEN=13
  Lane 2: RED=19, YELLOW=26, GREEN=21
"""

import time
import threading
import logging

log = logging.getLogger("Synnex.GPIO")

# ── Try to import RPi.GPIO ───────────────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not found — using console simulation")


# ══════════════════════════════════════════════════════════
#  PIN MAPPING
# ══════════════════════════════════════════════════════════
PIN_MAP = {
    1: {"red": 5,  "yellow": 6,  "green": 13},     # Lane 1
    2: {"red": 19, "yellow": 26, "green": 21},     # Lane 2
}

# Physical pin reference (for documentation)
PHYSICAL_PIN_MAP = {
    5:  29,     # Lane 1 RED    → Physical Pin 29
    6:  31,     # Lane 1 YELLOW → Physical Pin 31
    13: 33,     # Lane 1 GREEN  → Physical Pin 33
    19: 35,     # Lane 2 RED    → Physical Pin 35
    26: 37,     # Lane 2 YELLOW → Physical Pin 37
    21: 40,     # Lane 2 GREEN  → Physical Pin 40
}

# ── Transition timing ────────────────────────────────────
YELLOW_BLINK_COUNT = 3          # number of yellow blinks before red
YELLOW_BLINK_INTERVAL = 0.4     # seconds per blink cycle
ALL_RED_GAP = 1.0               # seconds of all-red between phases


# ══════════════════════════════════════════════════════════
#  GPIO SETUP & CLEANUP
# ══════════════════════════════════════════════════════════
def setup_gpio():
    """Initialise all GPIO pins as outputs, set all LEDs LOW."""
    if not GPIO_AVAILABLE:
        log.info("GPIO setup (simulated)")
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for lane_id, pins in PIN_MAP.items():
        for color, pin in pins.items():
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
            log.debug(f"  Pin {pin} (Lane {lane_id} {color}) → OUTPUT/LOW")

    log.info("GPIO pins initialised")


def cleanup_gpio():
    """Set all LEDs to RED, then release GPIO."""
    if not GPIO_AVAILABLE:
        log.info("GPIO cleanup (simulated)")
        return

    # Safety: set all to RED before releasing
    for lane_id, pins in PIN_MAP.items():
        GPIO.output(pins["red"],    GPIO.HIGH)
        GPIO.output(pins["yellow"], GPIO.LOW)
        GPIO.output(pins["green"],  GPIO.LOW)

    GPIO.cleanup()
    log.info("GPIO cleaned up — all lights RED")


# ══════════════════════════════════════════════════════════
#  TRAFFIC LIGHT CLASS
# ══════════════════════════════════════════════════════════
class TrafficLight:
    """
    Controls a single lane's traffic light (Red / Yellow / Green).
    Thread-safe — can be called from controller or manual override.
    """

    # LED state lookup: (red, yellow, green)
    _STATES = {
        "red":    (1, 0, 0),
        "yellow": (0, 1, 0),
        "green":  (0, 0, 1),
        "off":    (0, 0, 0),
    }

    def __init__(self, lane_id: int):
        self.lane_id = lane_id
        self._pins = PIN_MAP[lane_id]
        self._lock = threading.Lock()
        self.state = "off"

        # Start in RED for safety
        self.set("red")

    def set(self, color: str):
        """
        Set the traffic light to a specific color.
        Valid colors: 'red', 'yellow', 'green', 'off'
        """
        values = self._STATES.get(color)
        if values is None:
            log.error(f"Lane {self.lane_id}: invalid color '{color}'")
            return

        with self._lock:
            if GPIO_AVAILABLE:
                GPIO.output(self._pins["red"],    values[0])
                GPIO.output(self._pins["yellow"], values[1])
                GPIO.output(self._pins["green"],  values[2])
            self.state = color
            log.info(f"  Lane {self.lane_id} → {color.upper()}")

    def blink_yellow(self, count=YELLOW_BLINK_COUNT, interval=YELLOW_BLINK_INTERVAL):
        """
        Blink yellow LED as a warning before transitioning to red.
        Blocks for the duration of the blink sequence.
        """
        log.info(f"  Lane {self.lane_id}: yellow blink ({count}x)")
        for _ in range(count):
            self.set("yellow")
            time.sleep(interval)
            self.set("off")
            time.sleep(interval)

    def safe_transition_to_red(self):
        """
        Perform a safe Green → Yellow(blink) → Red transition.
        Should be called when ending a green phase.
        """
        self.blink_yellow()
        self.set("red")

    def get_state(self) -> str:
        """Return current light state (thread-safe)."""
        with self._lock:
            return self.state

    def __repr__(self):
        return f"TrafficLight(lane={self.lane_id}, state={self.state})"


def get_pin_info():
    """Return pin mapping as a dict for documentation/API."""
    info = {}
    for lane_id, pins in PIN_MAP.items():
        info[f"lane_{lane_id}"] = {
            color: {
                "bcm_pin": pin,
                "physical_pin": PHYSICAL_PIN_MAP.get(pin, "?"),
            }
            for color, pin in pins.items()
        }
    return info
