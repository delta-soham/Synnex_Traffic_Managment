#!/usr/bin/env python3
"""
camera.py — Video Capture & Vehicle Detection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Uses OpenCV background subtraction + contour detection
to count vehicles and classify traffic density.
Optimised for Raspberry Pi Zero 2W (low CPU).
"""

import time
import threading
import logging
import datetime
import cv2
import numpy as np

log = logging.getLogger("Synnex.Camera")

# ── Try to import Pi camera ──────────────────────────────
try:
    from picamera2 import Picamera2
    PICAM_AVAILABLE = True
except ImportError:
    PICAM_AVAILABLE = False

# ══════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════
RESOLUTION       = (640, 480)       # capture resolution
PROCESS_SIZE     = (320, 240)       # downscaled for processing (saves CPU)
JPEG_QUALITY     = 65               # MJPEG quality (lower = less bandwidth)
CAMERA_FPS       = 10               # target FPS (Pi Zero 2W friendly)

# Vehicle detection tuning
MIN_CONTOUR_AREA = 800              # minimum contour area to count as vehicle
MAX_CONTOUR_AREA = 50000            # maximum (filter out full-frame noise)
LEARNING_RATE    = 0.005            # background subtractor learning rate

# Traffic density thresholds (vehicles counted in last 60s)
DENSITY_LOW      = 3                # 0–3 vehicles/min  → LOW
DENSITY_MEDIUM   = 8                # 4–8 vehicles/min  → MEDIUM
                                    # >8  vehicles/min  → HIGH

# Lane regions of interest (ROI) — normalised coordinates [0..1]
# Default: left half = Lane 1, right half = Lane 2
# Adjust these for your actual camera mounting angle
LANE_ROIS = {
    1: {"x1": 0.0,  "y1": 0.3, "x2": 0.48, "y2": 0.9},   # left half
    2: {"x1": 0.52, "y1": 0.3, "x2": 1.0,  "y2": 0.9},   # right half
}


class VehicleDetector:
    """
    Lightweight vehicle detector using MOG2 background subtraction.
    Runs on a downscaled frame to keep CPU usage low on Pi Zero 2W.
    """

    def __init__(self):
        # Background subtractor — very efficient on ARM
        self._bg_sub = cv2.createBackgroundSubtractorMOG2(
            history=300,
            varThreshold=40,
            detectShadows=False,        # skip shadow detection (saves CPU)
        )
        # Morphology kernel for noise removal
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

        # Per-lane state
        self.lane_counts     = {1: 0, 2: 0}          # vehicles in current frame
        self.lane_totals     = {1: 0, 2: 0}          # cumulative since start
        self.lane_per_min    = {1: 0, 2: 0}          # rolling 60-second count
        self.lane_density    = {1: "LOW", 2: "LOW"}   # LOW / MEDIUM / HIGH
        self._lane_times     = {1: [], 2: []}         # timestamps for per-min calc
        self._lane_cooldown  = {1: 0.0, 2: 0.0}      # debounce per lane

        self._lock = threading.Lock()

    def process(self, frame):
        """
        Run detection on one frame. Returns annotated frame.
        Call this on every captured frame from the camera.
        """
        h, w = frame.shape[:2]

        # Downscale for processing
        small = cv2.resize(frame, PROCESS_SIZE)
        sh, sw = small.shape[:2]

        # Background subtraction
        fg_mask = self._bg_sub.apply(small, learningRate=LEARNING_RATE)

        # Morphology: remove noise, fill small gaps
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, self._kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, self._kernel)
        fg_mask = cv2.dilate(fg_mask, self._kernel, iterations=1)

        # Find contours
        contours, _ = cv2.findContours(
            fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        now = time.time()
        frame_counts = {1: 0, 2: 0}

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < MIN_CONTOUR_AREA or area > MAX_CONTOUR_AREA:
                continue

            # Bounding box on the small frame
            bx, by, bw, bh = cv2.boundingRect(cnt)

            # Scale back to original resolution for drawing
            scale_x = w / sw
            scale_y = h / sh
            ox = int(bx * scale_x)
            oy = int(by * scale_y)
            ow = int(bw * scale_x)
            oh = int(bh * scale_y)

            # Determine which lane this vehicle is in
            cx_norm = (bx + bw / 2) / sw   # normalised centre x
            cy_norm = (by + bh / 2) / sh   # normalised centre y

            lane_id = self._point_to_lane(cx_norm, cy_norm)
            if lane_id is None:
                continue

            frame_counts[lane_id] += 1

            # Draw bounding box + label on original frame
            color = (0, 255, 120) if lane_id == 1 else (255, 160, 40)
            cv2.rectangle(frame, (ox, oy), (ox + ow, oy + oh), color, 2)
            cv2.putText(frame, f"L{lane_id}", (ox, oy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # Update counts with debounce
        with self._lock:
            for lid in [1, 2]:
                self.lane_counts[lid] = frame_counts[lid]

                # Count a "new vehicle event" if we see vehicles after a gap
                if frame_counts[lid] > 0 and now - self._lane_cooldown[lid] > 1.5:
                    self.lane_totals[lid] += frame_counts[lid]
                    self._lane_times[lid].append(now)
                    self._lane_cooldown[lid] = now

                # Rolling 60-second window
                self._lane_times[lid] = [
                    t for t in self._lane_times[lid] if now - t <= 60
                ]
                self.lane_per_min[lid] = len(self._lane_times[lid])

                # Classify density
                vpm = self.lane_per_min[lid]
                if vpm <= DENSITY_LOW:
                    self.lane_density[lid] = "LOW"
                elif vpm <= DENSITY_MEDIUM:
                    self.lane_density[lid] = "MEDIUM"
                else:
                    self.lane_density[lid] = "HIGH"

        # Draw lane ROIs
        for lid, roi in LANE_ROIS.items():
            rx1 = int(roi["x1"] * w)
            ry1 = int(roi["y1"] * h)
            rx2 = int(roi["x2"] * w)
            ry2 = int(roi["y2"] * h)
            roi_color = (0, 200, 255) if lid == 1 else (255, 100, 200)
            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), roi_color, 1)
            cv2.putText(frame, f"Lane {lid}", (rx1 + 4, ry1 + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, roi_color, 1, cv2.LINE_AA)

        return frame

    def _point_to_lane(self, cx, cy):
        """Map a normalised point to a lane ID, or None if outside all ROIs."""
        for lid, roi in LANE_ROIS.items():
            if (roi["x1"] <= cx <= roi["x2"] and
                    roi["y1"] <= cy <= roi["y2"]):
                return lid
        return None

    def get_lane_data(self, lane_id):
        """Thread-safe snapshot of one lane's data."""
        with self._lock:
            return {
                "count":     self.lane_totals.get(lane_id, 0),
                "current":   self.lane_counts.get(lane_id, 0),
                "per_min":   self.lane_per_min.get(lane_id, 0),
                "density":   self.lane_density.get(lane_id, "LOW"),
            }

    def get_density(self, lane_id):
        """Return density string for a lane."""
        with self._lock:
            return self.lane_density.get(lane_id, "LOW")


class CameraStreamer(threading.Thread):
    """
    Camera capture thread.
    Captures frames from Pi Camera (or webcam as fallback),
    runs vehicle detection, and stores the latest JPEG for MJPEG streaming.
    """

    def __init__(self, detector: VehicleDetector):
        super().__init__(daemon=True, name="CameraThread")
        self.detector  = detector
        self._frame    = None           # latest JPEG bytes
        self._raw      = None           # latest raw BGR frame (for speed detection)
        self._lock     = threading.Lock()
        self._running  = True

    def run(self):
        if PICAM_AVAILABLE:
            self._run_picamera()
        else:
            self._run_opencv_fallback()

    def _run_picamera(self):
        """Use Picamera2 on Raspberry Pi."""
        try:
            cam = Picamera2()
            config = cam.create_video_configuration(
                main={"size": RESOLUTION, "format": "RGB888"},
                controls={"FrameRate": CAMERA_FPS},
            )
            cam.configure(config)
            cam.start()
            log.info(f"Pi Camera started: {RESOLUTION} @ {CAMERA_FPS}fps")
        except Exception as e:
            log.error(f"Pi Camera init failed: {e}")
            self._run_placeholder()
            return

        interval = 1.0 / CAMERA_FPS
        while self._running:
            try:
                t0 = time.time()
                rgb = cam.capture_array()
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                self._process_and_store(bgr)
                elapsed = time.time() - t0
                time.sleep(max(0, interval - elapsed))
            except Exception as e:
                log.error(f"Camera frame error: {e}")
                time.sleep(0.5)

        cam.stop()
        log.info("Pi Camera stopped")

    def _run_opencv_fallback(self):
        """Fallback: use USB webcam / laptop camera via OpenCV."""
        log.warning("Picamera2 not available — trying OpenCV VideoCapture")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            log.warning("No camera found — running placeholder")
            self._run_placeholder()
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  RESOLUTION[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        log.info("OpenCV camera started (fallback)")

        interval = 1.0 / CAMERA_FPS
        while self._running:
            t0 = time.time()
            ret, bgr = cap.read()
            if ret:
                self._process_and_store(bgr)
            elapsed = time.time() - t0
            time.sleep(max(0, interval - elapsed))

        cap.release()

    def _process_and_store(self, bgr_frame):
        """Run detection, add overlays, encode JPEG."""
        # Run vehicle detection (modifies frame in-place with annotations)
        annotated = self.detector.process(bgr_frame)

        # Add timestamp and LIVE indicator
        ts = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        cv2.putText(annotated, ts, (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(annotated, ts, (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 120), 1, cv2.LINE_AA)

        w = annotated.shape[1]
        cv2.putText(annotated, "LIVE", (w - 60, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 200), 2, cv2.LINE_AA)
        cv2.putText(annotated, "LIVE", (w - 60, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 120, 255), 1, cv2.LINE_AA)

        # Density overlay per lane
        for lid in [1, 2]:
            data = self.detector.get_lane_data(lid)
            label = f"L{lid}: {data['density']} ({data['per_min']}/min)"
            y_pos = 22 + lid * 20
            cv2.putText(annotated, label, (10, y_pos + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255),
                        1, cv2.LINE_AA)

        # Encode to JPEG
        _, buf = cv2.imencode(".jpg", annotated,
                              [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        with self._lock:
            self._frame = buf.tobytes()
            self._raw = bgr_frame.copy()

    def _run_placeholder(self):
        """Generate a static 'no camera' frame."""
        placeholder = np.zeros((RESOLUTION[1], RESOLUTION[0], 3), dtype=np.uint8)
        cv2.putText(placeholder, "NO CAMERA", (180, 250),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 2, cv2.LINE_AA)
        _, buf = cv2.imencode(".jpg", placeholder,
                              [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        with self._lock:
            self._frame = buf.tobytes()
            self._raw = placeholder
        while self._running:
            time.sleep(1)

    def get_frame(self):
        """Get latest JPEG frame (for MJPEG streaming)."""
        with self._lock:
            return self._frame

    def get_raw_frame(self):
        """Get latest raw BGR frame (for speed detection)."""
        with self._lock:
            return self._raw.copy() if self._raw is not None else None

    def stop(self):
        self._running = False


def mjpeg_generator(camera: CameraStreamer):
    """
    MJPEG multipart generator for Flask streaming response.
    Yields JPEG frames separated by multipart boundaries.
    """
    while True:
        frame = camera.get_frame()
        if frame:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(1.0 / CAMERA_FPS)
