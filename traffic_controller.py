#!/usr/bin/env python3
"""
traffic_controller.py — Round-Robin Traffic Control
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Implements round-robin scheduling for multiple lanes.
Dynamically adjusts green light duration based on
camera-detected vehicle density.

Modes:
  AUTOMATIC — fully camera-driven decisions
  MANUAL    — user controls lights from dashboard
"""

import time
import threading
import logging

from gpio_control import TrafficLight, ALL_RED_GAP
from camera import VehicleDetector

log = logging.getLogger("Synnex.Controller")

# ══════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════

# Green light durations (seconds) based on density
GREEN_DURATION = {
    "LOW":    10,       # light traffic → short green
    "MEDIUM": 20,       # moderate traffic → standard green
    "HIGH":   35,       # heavy traffic → extended green
}

MIN_GREEN_SEC   = 8         # absolute minimum green time
MAX_GREEN_SEC   = 45        # absolute maximum green time (prevents starvation)
POLL_INTERVAL   = 0.5       # how often to check conditions during green phase

NUM_LANES       = 2         # number of lanes in the intersection


class TrafficController(threading.Thread):
    """
    Round-robin traffic controller.

    In AUTOMATIC mode:
      - Cycles through lanes using round-robin
      - Adjusts green duration based on detected traffic density
      - Always ensures safe transitions (Green → Yellow → Red)

    In MANUAL mode:
      - Ignores automatic scheduling
      - User controls lights via dashboard API
    """

    def __init__(self, lights: dict, detector: VehicleDetector):
        """
        Args:
            lights:   dict mapping lane_id → TrafficLight instance
            detector: VehicleDetector instance (from camera.py)
        """
        super().__init__(daemon=True, name="TrafficController")
        self.lights   = lights          # {1: TrafficLight, 2: TrafficLight}
        self.detector = detector
        self._running = True
        self._lock    = threading.Lock()

        # Mode: "automatic" or "manual"
        self._mode = "automatic"

        # Current state (read by dashboard)
        self.current_lane   = 1
        self.phase          = "initialising"
        self.phase_start    = time.time()
        self.last_trigger   = "—"
        self.green_duration = GREEN_DURATION["LOW"]

    # ── Mode control ─────────────────────────────────────
    @property
    def mode(self):
        with self._lock:
            return self._mode

    @mode.setter
    def mode(self, value):
        with self._lock:
            if value in ("automatic", "manual"):
                self._mode = value
                log.info(f"Mode → {value.upper()}")

    def set_manual_light(self, lane_id: int, color: str):
        """
        Manually set a specific lane's light. Only works in MANUAL mode.
        Returns True if successful, False if not in manual mode.
        """
        if self.mode != "manual":
            return False

        if lane_id not in self.lights:
            log.warning(f"Invalid lane_id: {lane_id}")
            return False

        if color not in ("red", "yellow", "green"):
            log.warning(f"Invalid color: {color}")
            return False

        self.lights[lane_id].set(color)
        self.phase = f"manual_lane{lane_id}_{color}"
        self.last_trigger = f"manual override → Lane {lane_id} {color.upper()}"
        log.info(f"Manual: Lane {lane_id} → {color.upper()}")
        return True

    def set_all_red(self):
        """Emergency: set all lights to RED immediately."""
        for light in self.lights.values():
            light.set("red")
        self.phase = "all_red"
        self.last_trigger = "all red (emergency/manual)"
        log.warning("ALL LIGHTS → RED")

    # ── State snapshot for dashboard ─────────────────────
    def get_state(self):
        """Thread-safe state snapshot for the dashboard API."""
        with self._lock:
            return {
                "mode":           self._mode,
                "current_lane":   self.current_lane,
                "phase":          self.phase,
                "phase_elapsed":  round(time.time() - self.phase_start, 1),
                "green_duration": self.green_duration,
                "last_trigger":   self.last_trigger,
                "signals": {
                    lid: light.get_state()
                    for lid, light in self.lights.items()
                },
            }

    # ── Main loop ────────────────────────────────────────
    def run(self):
        log.info("Traffic Controller started")

        # Start with all RED
        self.set_all_red()
        time.sleep(1)

        lane_order = list(range(1, NUM_LANES + 1))   # [1, 2]
        idx = 0

        while self._running:
            # In manual mode, just idle — user controls lights
            if self.mode == "manual":
                self.phase = "manual"
                time.sleep(POLL_INTERVAL)
                continue

            # ── AUTOMATIC MODE ────────────────────────
            lane_id = lane_order[idx]
            self.current_lane = lane_id

            # Determine green duration from traffic density
            density = self.detector.get_density(lane_id)
            duration = GREEN_DURATION.get(density, GREEN_DURATION["LOW"])
            duration = max(MIN_GREEN_SEC, min(MAX_GREEN_SEC, duration))
            self.green_duration = duration

            # ── GREEN PHASE ──────────────────────────
            reason = self._green_phase(lane_id, duration)

            if reason == "stopped":
                break

            # ── TRANSITION ───────────────────────────
            if self.mode == "automatic":       # could have switched to manual mid-phase
                self.lights[lane_id].safe_transition_to_red()
                self.phase = "transition"

                # All-red safety gap
                time.sleep(ALL_RED_GAP)

            # Next lane
            idx = (idx + 1) % len(lane_order)

        log.info("Traffic Controller stopped")

    def _green_phase(self, lane_id, duration):
        """
        Hold a lane GREEN for `duration` seconds.
        Checks density dynamically and may extend/shorten.
        Returns: 'completed' | 'mode_switch' | 'stopped'
        """
        # Set active lane GREEN, all others RED
        for lid, light in self.lights.items():
            if lid == lane_id:
                light.set("green")
            else:
                light.set("red")

        self.phase = f"lane{lane_id}_green"
        self.phase_start = time.time()

        density = self.detector.get_density(lane_id)
        log.info(f"Lane {lane_id} GREEN for {duration}s "
                 f"(density={density})")
        self.last_trigger = f"Lane {lane_id}: {density} density → {duration}s green"

        while self._running:
            elapsed = time.time() - self.phase_start

            # Check if mode switched to manual
            if self.mode != "automatic":
                log.info(f"Lane {lane_id}: mode switched to MANUAL")
                return "mode_switch"

            # Dynamic re-evaluation: if density changed, adjust remaining time
            current_density = self.detector.get_density(lane_id)
            new_target = GREEN_DURATION.get(current_density, duration)
            new_target = max(MIN_GREEN_SEC, min(MAX_GREEN_SEC, new_target))

            # Only extend if density increased, never shorten below MIN
            if new_target > duration and elapsed < MIN_GREEN_SEC:
                duration = new_target
                self.green_duration = duration
                log.info(f"Lane {lane_id}: density→{current_density}, "
                         f"extended to {duration}s")

            # Time's up
            if elapsed >= duration:
                log.info(f"Lane {lane_id}: green phase complete "
                         f"({elapsed:.1f}s, density={current_density})")
                self.last_trigger = (
                    f"Lane {lane_id}: {elapsed:.0f}s elapsed "
                    f"(density={current_density})"
                )
                return "completed"

            time.sleep(POLL_INTERVAL)

        return "stopped"

    def stop(self):
        """Signal the controller to stop."""
        self._running = False
        log.info("Controller stop requested")
