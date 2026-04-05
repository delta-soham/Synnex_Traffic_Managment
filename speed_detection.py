#!/usr/bin/env python3
"""
speed_detection.py — Camera-Based Speed Estimation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Estimates vehicle speed using frame difference + centroid tracking.
Works by measuring how far detected objects move between frames,
then converting pixel displacement to approximate km/h.

Logs vehicles exceeding a configurable speed threshold.

Limitations:
  - Accuracy depends on camera angle and calibration
  - This is a ROUGH estimate, not radar-grade
  - Good enough for educational / demonstration purposes

Optimised for Pi Zero 2W: only processes every Nth frame.
"""

import time
import threading
import logging
import cv2
import numpy as np
from collections import deque

from data_logger import DataLogger

log = logging.getLogger("Synnex.Speed")

# ══════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════
SPEED_LIMIT_KMPH     = 40        # speed violation threshold (km/h)
PROCESS_EVERY_N      = 3         # process every Nth frame (saves CPU)
TRACK_HISTORY        = 10        # max tracked positions per object

# Calibration — these convert pixel displacement to real-world speed
# You MUST calibrate these for your specific camera setup:
#   1. Measure a known distance in the real world (e.g. 5 metres)
#   2. Count how many pixels that distance spans in the camera frame
#   3. Set PIXELS_PER_METRE accordingly
PIXELS_PER_METRE     = 30.0      # pixels per real-world metre (calibrate!)
FRAME_INTERVAL_SEC   = 0.15      # approximate time between processed frames

# Detection tuning
MIN_CONTOUR_AREA     = 600
MAX_CONTOUR_AREA     = 40000
MAX_MATCH_DISTANCE   = 80        # max pixel distance to match same object


class TrackedObject:
    """A tracked moving object with position history."""

    def __init__(self, obj_id, centroid):
        self.obj_id    = obj_id
        self.positions  = deque(maxlen=TRACK_HISTORY)
        self.timestamps = deque(maxlen=TRACK_HISTORY)
        self.speed_kmph = 0.0
        self.last_seen  = time.time()

        self.positions.append(centroid)
        self.timestamps.append(time.time())

    def update(self, centroid):
        """Add new position measurement."""
        now = time.time()
        self.positions.append(centroid)
        self.timestamps.append(now)
        self.last_seen = now
        self._calc_speed()

    def _calc_speed(self):
        """
        Estimate speed from recent position history.
        Uses average displacement over last few frames.
        """
        if len(self.positions) < 2:
            return

        # Use last 2 positions for speed calculation
        p1 = self.positions[-2]
        p2 = self.positions[-1]
        t1 = self.timestamps[-2]
        t2 = self.timestamps[-1]

        dt = t2 - t1
        if dt <= 0:
            return

        # Pixel displacement
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        pixel_dist = np.sqrt(dx * dx + dy * dy)

        # Convert to real-world speed
        metres = pixel_dist / PIXELS_PER_METRE
        speed_ms = metres / dt
        self.speed_kmph = round(speed_ms * 3.6, 1)     # m/s → km/h

    @property
    def is_stale(self):
        """Object hasn't been seen for >2 seconds."""
        return time.time() - self.last_seen > 2.0


class SpeedDetector(threading.Thread):
    """
    Background thread that periodically grabs frames from the camera
    and tracks moving objects to estimate their speed.
    """

    def __init__(self, camera, data_logger: DataLogger = None):
        """
        Args:
            camera:      CameraStreamer instance (provides raw frames)
            data_logger: DataLogger instance for recording violations
        """
        super().__init__(daemon=True, name="SpeedDetector")
        self.camera      = camera
        self.data_logger = data_logger
        self._running    = True
        self._lock       = threading.Lock()

        # Background subtractor for motion detection
        self._bg_sub = cv2.createBackgroundSubtractorMOG2(
            history=200,
            varThreshold=50,
            detectShadows=False,
        )
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

        # Tracked objects
        self._objects = {}          # obj_id → TrackedObject
        self._next_id = 0
        self._frame_count = 0

        # Public data
        self.violations = []        # list of violation dicts
        self.current_speeds = {}    # obj_id → speed_kmph (active objects)

    def run(self):
        log.info("Speed Detector started")

        while self._running:
            self._frame_count += 1

            # Only process every Nth frame to save CPU
            if self._frame_count % PROCESS_EVERY_N != 0:
                time.sleep(0.05)
                continue

            raw = self.camera.get_raw_frame()
            if raw is None:
                time.sleep(0.2)
                continue

            self._process_frame(raw)
            time.sleep(FRAME_INTERVAL_SEC)

        log.info("Speed Detector stopped")

    def _process_frame(self, frame):
        """Detect moving objects and update tracking."""
        # Downscale for speed
        small = cv2.resize(frame, (320, 240))
        grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        grey = cv2.GaussianBlur(grey, (5, 5), 0)

        # Background subtraction
        fg = self._bg_sub.apply(grey, learningRate=0.008)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel)

        # Find contours
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)

        # Extract centroids of detected objects
        centroids = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if MIN_CONTOUR_AREA < area < MAX_CONTOUR_AREA:
                M = cv2.moments(cnt)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    centroids.append((cx, cy))

        # Match centroids to existing tracked objects (nearest neighbour)
        matched_ids = set()
        for centroid in centroids:
            best_id = None
            best_dist = MAX_MATCH_DISTANCE

            for obj_id, obj in self._objects.items():
                if obj_id in matched_ids:
                    continue
                last_pos = obj.positions[-1]
                dist = np.sqrt(
                    (centroid[0] - last_pos[0]) ** 2 +
                    (centroid[1] - last_pos[1]) ** 2
                )
                if dist < best_dist:
                    best_dist = dist
                    best_id = obj_id

            if best_id is not None:
                # Update existing object
                self._objects[best_id].update(centroid)
                matched_ids.add(best_id)
            else:
                # New object
                new_id = self._next_id
                self._next_id += 1
                self._objects[new_id] = TrackedObject(new_id, centroid)

        # Check for speed violations and update public data
        with self._lock:
            self.current_speeds = {}
            stale_ids = []

            for obj_id, obj in self._objects.items():
                if obj.is_stale:
                    stale_ids.append(obj_id)
                    continue

                self.current_speeds[obj_id] = obj.speed_kmph

                # Check for speed violation
                if obj.speed_kmph > SPEED_LIMIT_KMPH:
                    violation = {
                        "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
                        "speed_kmph": obj.speed_kmph,
                        "object_id":  obj_id,
                    }
                    # Avoid duplicate violations for same object
                    recent = [v for v in self.violations
                              if v["object_id"] == obj_id
                              and time.time() - time.mktime(
                                  time.strptime(v["timestamp"],
                                                "%Y-%m-%d %H:%M:%S")) < 5]
                    if not recent:
                        self.violations.append(violation)
                        log.warning(
                            f"SPEED VIOLATION: {obj.speed_kmph:.1f} km/h "
                            f"(limit: {SPEED_LIMIT_KMPH} km/h)"
                        )
                        # Log to data store
                        if self.data_logger:
                            self.data_logger.log_speed_violation(
                                obj.speed_kmph, SPEED_LIMIT_KMPH
                            )

            # Remove stale objects
            for sid in stale_ids:
                del self._objects[sid]

    def get_violations(self, limit=50):
        """Get recent speed violations (newest first)."""
        with self._lock:
            return list(reversed(self.violations[-limit:]))

    def get_max_speed(self):
        """Get the highest currently detected speed."""
        with self._lock:
            if self.current_speeds:
                return max(self.current_speeds.values())
            return 0.0

    def get_speeds(self):
        """Get all current object speeds."""
        with self._lock:
            return dict(self.current_speeds)

    def stop(self):
        self._running = False
