#!/usr/bin/env python3
"""
data_logger.py — Data Logging (SQLite)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stores all traffic data in a local SQLite database:
  - Vehicle counts per lane
  - Traffic density readings
  - Speed violations
  - Signal state changes

Provides query methods for the dashboard API.
Designed for low overhead on Raspberry Pi Zero 2W.
"""

import os
import time
import sqlite3
import threading
import logging

log = logging.getLogger("Synnex.DataLogger")

# Default database path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "traffic_data.db")


class DataLogger:
    """
    Thread-safe SQLite logger for traffic data.
    Uses WAL mode for better concurrent read/write performance.
    """

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        log.info(f"DataLogger initialised: {self.db_path}")

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript("""
                -- Vehicle count snapshots (periodic)
                CREATE TABLE IF NOT EXISTS vehicle_counts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    lane_id    INTEGER NOT NULL,
                    count      INTEGER NOT NULL,
                    per_min    INTEGER NOT NULL DEFAULT 0,
                    density    TEXT NOT NULL DEFAULT 'LOW'
                );

                -- Speed violation events
                CREATE TABLE IF NOT EXISTS speed_violations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    speed_kmph  REAL NOT NULL,
                    limit_kmph  REAL NOT NULL
                );

                -- Signal state changes
                CREATE TABLE IF NOT EXISTS signal_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    lane_id    INTEGER NOT NULL,
                    new_state  TEXT NOT NULL,
                    trigger    TEXT DEFAULT ''
                );

                -- Density readings (periodic)
                CREATE TABLE IF NOT EXISTS density_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    lane_id    INTEGER NOT NULL,
                    density    TEXT NOT NULL,
                    vehicle_count INTEGER NOT NULL DEFAULT 0
                );

                -- Create indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_vc_time
                    ON vehicle_counts(timestamp);
                CREATE INDEX IF NOT EXISTS idx_sv_time
                    ON speed_violations(timestamp);
                CREATE INDEX IF NOT EXISTS idx_sl_time
                    ON signal_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_dl_time
                    ON density_log(timestamp);
            """)
        log.info("Database tables ready")

    def _connect(self):
        """Create a new connection (thread-safe with WAL)."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── WRITE METHODS ────────────────────────────────────

    def log_vehicle_count(self, lane_id, count, per_min, density):
        """Record a vehicle count snapshot for a lane."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """INSERT INTO vehicle_counts
                           (lane_id, count, per_min, density)
                           VALUES (?, ?, ?, ?)""",
                        (lane_id, count, per_min, density)
                    )
            except Exception as e:
                log.error(f"Failed to log vehicle count: {e}")

    def log_speed_violation(self, speed_kmph, limit_kmph):
        """Record a speed violation event."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """INSERT INTO speed_violations
                           (speed_kmph, limit_kmph) VALUES (?, ?)""",
                        (speed_kmph, limit_kmph)
                    )
                log.info(f"Logged speed violation: {speed_kmph:.1f} km/h")
            except Exception as e:
                log.error(f"Failed to log speed violation: {e}")

    def log_signal_change(self, lane_id, new_state, trigger=""):
        """Record a signal state change."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """INSERT INTO signal_log
                           (lane_id, new_state, trigger) VALUES (?, ?, ?)""",
                        (lane_id, new_state, trigger)
                    )
            except Exception as e:
                log.error(f"Failed to log signal change: {e}")

    def log_density(self, lane_id, density, vehicle_count):
        """Record a density reading for a lane."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """INSERT INTO density_log
                           (lane_id, density, vehicle_count)
                           VALUES (?, ?, ?)""",
                        (lane_id, density, vehicle_count)
                    )
            except Exception as e:
                log.error(f"Failed to log density: {e}")

    # ── READ METHODS (for dashboard API) ─────────────────

    def get_recent_violations(self, limit=50):
        """Get the most recent speed violations."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT timestamp, speed_kmph, limit_kmph
                       FROM speed_violations
                       ORDER BY id DESC LIMIT ?""",
                    (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            log.error(f"Query error: {e}")
            return []

    def get_recent_counts(self, lane_id=None, limit=100):
        """Get recent vehicle count snapshots."""
        try:
            with self._connect() as conn:
                if lane_id is not None:
                    rows = conn.execute(
                        """SELECT timestamp, lane_id, count, per_min, density
                           FROM vehicle_counts
                           WHERE lane_id = ?
                           ORDER BY id DESC LIMIT ?""",
                        (lane_id, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT timestamp, lane_id, count, per_min, density
                           FROM vehicle_counts
                           ORDER BY id DESC LIMIT ?""",
                        (limit,)
                    ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            log.error(f"Query error: {e}")
            return []

    def get_signal_history(self, limit=50):
        """Get recent signal changes."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT timestamp, lane_id, new_state, trigger
                       FROM signal_log
                       ORDER BY id DESC LIMIT ?""",
                    (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            log.error(f"Query error: {e}")
            return []

    def get_stats_summary(self):
        """Get aggregate statistics for the dashboard."""
        try:
            with self._connect() as conn:
                total_violations = conn.execute(
                    "SELECT COUNT(*) FROM speed_violations"
                ).fetchone()[0]

                max_speed = conn.execute(
                    "SELECT MAX(speed_kmph) FROM speed_violations"
                ).fetchone()[0] or 0

                total_vehicles = {}
                for lane_id in [1, 2]:
                    row = conn.execute(
                        """SELECT MAX(count) FROM vehicle_counts
                           WHERE lane_id = ?""",
                        (lane_id,)
                    ).fetchone()
                    total_vehicles[lane_id] = row[0] if row[0] else 0

                return {
                    "total_violations": total_violations,
                    "max_speed_ever":   round(max_speed, 1),
                    "total_vehicles":   total_vehicles,
                }
        except Exception as e:
            log.error(f"Stats query error: {e}")
            return {
                "total_violations": 0,
                "max_speed_ever": 0,
                "total_vehicles": {1: 0, 2: 0},
            }

    def cleanup_old_data(self, days=7):
        """Delete records older than N days to save disk space."""
        with self._lock:
            try:
                with self._connect() as conn:
                    cutoff = f"datetime('now', '-{days} days')"
                    for table in ["vehicle_counts", "speed_violations",
                                  "signal_log", "density_log"]:
                        conn.execute(
                            f"DELETE FROM {table} WHERE timestamp < {cutoff}"
                        )
                    conn.execute("VACUUM")
                log.info(f"Cleaned up data older than {days} days")
            except Exception as e:
                log.error(f"Cleanup error: {e}")
