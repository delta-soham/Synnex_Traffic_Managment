#!/usr/bin/env python3
"""
dashboard.py — Professional Flask Web Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Premium traffic management dashboard:
  - Live camera feed (MJPEG)
  - Vehicle count per lane with animated gauges
  - Traffic density display
  - Animated signal status
  - Automatic / Manual mode toggle
  - Manual override buttons
  - Speed violation logs
  - Real-time system metrics

Served on http://<PI_IP>:5000
"""

import time
import copy
import logging
from flask import Flask, Response, render_template_string, jsonify, request

from camera import CameraStreamer, VehicleDetector, mjpeg_generator
from traffic_controller import TrafficController
from speed_detection import SpeedDetector
from data_logger import DataLogger
from gpio_control import get_pin_info

log = logging.getLogger("Synnex.Dashboard")

# ══════════════════════════════════════════════════════════
#  FLASK APP
# ══════════════════════════════════════════════════════════
app = Flask(__name__)

# These will be set by main.py before app.run()
camera: CameraStreamer = None
detector: VehicleDetector = None
controller: TrafficController = None
speed_det: SpeedDetector = None
data_logger: DataLogger = None


# ═══════════════════════════════════════════════════════════════
#  DASHBOARD HTML — PREMIUM UI
# ═══════════════════════════════════════════════════════════════
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Synnex — Smart Traffic Management</title>
<meta name="description" content="Real-time AI-powered traffic management dashboard with live camera feed, vehicle counting, and intelligent signal control."/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
/* ═══════════════════════════════════════════════
   CSS CUSTOM PROPERTIES
   ═══════════════════════════════════════════════ */
:root {
  --bg-primary:    #04060b;
  --bg-secondary:  #080d15;
  --bg-card:       #0b1120;
  --bg-card-hover: #0f1628;
  --bg-elevated:   #111a2e;
  --bg-glass:      rgba(11, 17, 32, 0.72);

  --border:        rgba(255, 255, 255, 0.05);
  --border-subtle: rgba(255, 255, 255, 0.03);
  --border-accent: rgba(99, 179, 237, 0.15);

  --accent:        #63b3ed;
  --accent-bright: #90cdf4;
  --cyan:          #0bc5ea;
  --green:         #38d988;
  --green-dim:     rgba(56, 217, 136, 0.15);
  --red:           #fc5c65;
  --red-dim:       rgba(252, 92, 101, 0.12);
  --yellow:        #fed330;
  --yellow-dim:    rgba(254, 211, 48, 0.12);
  --orange:        #fd9644;
  --purple:        #a55eea;

  --text:          #e8edf5;
  --text-secondary:#94a3b8;
  --text-muted:    #5a6a80;
  --text-dim:      #3a4a5c;

  --shadow-sm:     0 1px 3px rgba(0,0,0,0.3);
  --shadow-md:     0 4px 16px rgba(0,0,0,0.35);
  --shadow-lg:     0 8px 32px rgba(0,0,0,0.4);
  --shadow-glow:   0 0 30px rgba(99, 179, 237, 0.06);

  --radius:        16px;
  --radius-sm:     10px;
  --radius-xs:     6px;
  --radius-pill:   50px;

  --nav-h:         60px;
  --transition:    all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

/* ═══════════════════════════════════════════════
   RESET & BASE
   ═══════════════════════════════════════════════ */
*, *::before, *::after {
  margin: 0; padding: 0; box-sizing: border-box;
}
html { scroll-behavior: smooth; }
body {
  background: var(--bg-primary);
  color: var(--text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  min-height: 100vh;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
}

/* Ambient background effects */
body::before {
  content: '';
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(ellipse 80% 50% at 10% -10%, rgba(99,179,237,0.06) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 90% 110%, rgba(11,197,234,0.04) 0%, transparent 60%),
    radial-gradient(ellipse 50% 50% at 50% 50%, rgba(56,217,136,0.015) 0%, transparent 70%);
}
body::after {
  content: '';
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(99,179,237,0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(99,179,237,0.015) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 70%);
  -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 70%);
}

/* ═══════════════════════════════════════════════
   NAVIGATION
   ═══════════════════════════════════════════════ */
nav {
  position: sticky; top: 0; z-index: 100;
  height: var(--nav-h);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 32px;
  background: rgba(4, 6, 11, 0.8);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(24px) saturate(1.5);
  -webkit-backdrop-filter: blur(24px) saturate(1.5);
}
.brand {
  display: flex; align-items: center; gap: 10px;
}
.brand-icon {
  width: 34px; height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--accent) 0%, var(--cyan) 100%);
  display: flex; align-items: center; justify-content: center;
  font-size: 17px;
  box-shadow: 0 0 20px rgba(99,179,237,0.2);
}
.brand-text {
  font-size: 18px; font-weight: 800; letter-spacing: -0.5px;
  color: var(--text);
}
.brand-text span {
  background: linear-gradient(135deg, var(--accent) 0%, var(--cyan) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.nav-center {
  display: flex; align-items: center; gap: 20px;
}
.nav-pill {
  display: flex; align-items: center; gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px; font-weight: 500;
  padding: 6px 14px; border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: rgba(255,255,255,0.02);
  color: var(--text-secondary);
  transition: var(--transition);
}
.nav-pill.live {
  border-color: rgba(56,217,136,0.2);
  color: var(--green);
  background: rgba(56,217,136,0.05);
}
.dot-pulse {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 8px var(--green);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.3; transform: scale(0.8); }
}
.nav-right {
  display: flex; align-items: center; gap: 12px;
}
.clock {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px; color: var(--text-muted);
  letter-spacing: 0.5px;
}

/* ═══════════════════════════════════════════════
   MAIN GRID LAYOUT
   ═══════════════════════════════════════════════ */
.dashboard {
  position: relative; z-index: 1;
  max-width: 1440px; margin: 0 auto;
  padding: 20px 24px 40px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.full-width { grid-column: 1 / -1; }

/* ═══════════════════════════════════════════════
   CARD SYSTEM
   ═══════════════════════════════════════════════ */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px;
  position: relative;
  overflow: hidden;
  transition: var(--transition);
}
.card::before {
  content: '';
  position: absolute; inset: 0;
  border-radius: var(--radius);
  padding: 1px;
  background: linear-gradient(135deg, rgba(99,179,237,0.08) 0%, transparent 50%, transparent 100%);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.4s;
}
.card:hover::before { opacity: 1; }
.card:hover {
  border-color: rgba(99,179,237,0.08);
  box-shadow: var(--shadow-glow);
}

.card-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 18px;
}
.card-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 10px; font-weight: 700;
  letter-spacing: 2.5px; text-transform: uppercase;
  color: var(--text-muted);
}
.card-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px rgba(99,179,237,0.3);
}
.card-dot.green { background: var(--green); box-shadow: 0 0 8px rgba(56,217,136,0.3); }
.card-dot.red { background: var(--red); box-shadow: 0 0 8px rgba(252,92,101,0.3); }
.card-dot.orange { background: var(--orange); box-shadow: 0 0 8px rgba(253,150,68,0.3); }
.card-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; font-weight: 600;
  padding: 3px 10px; border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

/* ═══════════════════════════════════════════════
   ALERT BANNER
   ═══════════════════════════════════════════════ */
.alert-banner {
  display: none; align-items: center; gap: 12px;
  padding: 14px 22px; border-radius: var(--radius);
  background: linear-gradient(135deg, rgba(252,92,101,0.08) 0%, rgba(252,92,101,0.03) 100%);
  border: 1px solid rgba(252,92,101,0.2);
  color: var(--red);
  font-size: 13px; font-weight: 600;
  animation: alertSlide 0.4s ease-out;
}
@keyframes alertSlide {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.alert-icon {
  width: 32px; height: 32px; border-radius: 8px;
  background: rgba(252,92,101,0.12);
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; flex-shrink: 0;
}

/* ═══════════════════════════════════════════════
   MODE CONTROL
   ═══════════════════════════════════════════════ */
.mode-controls {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.mode-btn-group {
  display: flex; background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm); overflow: hidden;
}
.mode-btn {
  padding: 10px 22px;
  border: none; background: transparent;
  color: var(--text-muted);
  font-family: 'Inter', sans-serif;
  font-size: 13px; font-weight: 600;
  cursor: pointer;
  display: flex; align-items: center; gap: 7px;
  transition: var(--transition);
  position: relative;
}
.mode-btn:not(:last-child)::after {
  content: ''; position: absolute; right: 0; top: 20%; height: 60%;
  width: 1px; background: var(--border);
}
.mode-btn:hover { color: var(--text-secondary); background: rgba(255,255,255,0.02); }
.mode-btn.active {
  color: var(--accent);
  background: rgba(99,179,237,0.08);
}
.mode-btn.active .mode-indicator {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px rgba(99,179,237,0.5);
}
.emergency-btn {
  padding: 10px 20px; border-radius: var(--radius-sm);
  border: 1px solid rgba(252,92,101,0.2);
  background: rgba(252,92,101,0.06);
  color: var(--red);
  font-family: 'Inter', sans-serif;
  font-size: 13px; font-weight: 600;
  cursor: pointer;
  display: flex; align-items: center; gap: 6px;
  transition: var(--transition);
  margin-left: auto;
}
.emergency-btn:hover {
  background: rgba(252,92,101,0.12);
  border-color: rgba(252,92,101,0.35);
  box-shadow: 0 0 20px rgba(252,92,101,0.1);
}
.mode-status {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px; color: var(--text-dim);
  margin-left: 8px;
}

/* ═══════════════════════════════════════════════
   SYSTEM INFO BAR
   ═══════════════════════════════════════════════ */
.info-bar {
  display: flex; align-items: stretch; gap: 1px;
  background: var(--border);
  border-radius: var(--radius-sm); overflow: hidden;
}
.info-item {
  flex: 1;
  background: var(--bg-elevated);
  padding: 12px 16px;
  min-width: 0;
}
.info-label {
  font-size: 9px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 4px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.info-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px; font-weight: 500;
  color: var(--accent);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* ═══════════════════════════════════════════════
   SIGNAL CARD (LANE CARD)
   ═══════════════════════════════════════════════ */
.lane-card { position: relative; }
.lane-card .accent-bar {
  position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent 80%);
  opacity: 0.6;
}
.lane-card.lane-2 .accent-bar {
  background: linear-gradient(90deg, var(--cyan), transparent 80%);
}
.lane-card.lane-2 .card-dot { background: var(--cyan); box-shadow: 0 0 8px rgba(11,197,234,0.3); }

.signal-display {
  display: flex; align-items: center; gap: 20px;
  margin-bottom: 16px;
}

/* Traffic Light Housing */
.traffic-light {
  width: 42px; padding: 8px 0;
  background: linear-gradient(180deg, #1a1f2e 0%, #12172380 100%);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 22px;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), var(--shadow-md);
}
.light-bulb {
  width: 26px; height: 26px; border-radius: 50%;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.04);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}
.light-bulb::after {
  content: ''; position: absolute; inset: 3px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, rgba(255,255,255,0.15) 0%, transparent 60%);
  opacity: 0; transition: opacity 0.4s;
}
.light-bulb.on-red {
  background: var(--red);
  box-shadow: 0 0 16px var(--red), 0 0 40px rgba(252,92,101,0.25), inset 0 -2px 4px rgba(0,0,0,0.2);
  border-color: rgba(252,92,101,0.4);
}
.light-bulb.on-red::after { opacity: 1; }
.light-bulb.on-yellow {
  background: var(--yellow);
  box-shadow: 0 0 16px var(--yellow), 0 0 40px rgba(254,211,48,0.25), inset 0 -2px 4px rgba(0,0,0,0.2);
  border-color: rgba(254,211,48,0.4);
}
.light-bulb.on-yellow::after { opacity: 1; }
.light-bulb.on-green {
  background: var(--green);
  box-shadow: 0 0 16px var(--green), 0 0 40px rgba(56,217,136,0.25), inset 0 -2px 4px rgba(0,0,0,0.2);
  border-color: rgba(56,217,136,0.3);
}
.light-bulb.on-green::after { opacity: 1; }

.signal-info { flex: 1; }
.lane-name {
  font-size: 26px; font-weight: 800; letter-spacing: -1px;
  line-height: 1.1; margin-bottom: 6px;
  background: linear-gradient(135deg, var(--text) 0%, var(--text-secondary) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.signal-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sig-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; font-weight: 700;
  padding: 3px 10px; border-radius: var(--radius-xs);
  letter-spacing: 0.5px;
}
.sig-badge.red    { background: var(--red-dim);    color: var(--red); }
.sig-badge.yellow { background: var(--yellow-dim); color: var(--yellow); }
.sig-badge.green  { background: var(--green-dim);  color: var(--green); }
.sig-badge.off    { background: rgba(90,106,128,0.12); color: var(--text-muted); }

.density-chip {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; font-weight: 700;
  padding: 3px 10px; border-radius: var(--radius-xs);
  letter-spacing: 0.5px;
}
.density-chip.LOW    { background: var(--green-dim); color: var(--green); }
.density-chip.MEDIUM { background: var(--yellow-dim); color: var(--yellow); }
.density-chip.HIGH   { background: var(--red-dim); color: var(--red); }

/* ═══════════════════════════════════════════════
   METRICS GRID
   ═══════════════════════════════════════════════ */
.metrics-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 8px; margin-top: 14px;
}
.metric {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  transition: var(--transition);
}
.metric:hover {
  border-color: var(--border);
  background: var(--bg-elevated);
}
.metric-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px; font-weight: 700;
  line-height: 1;
  transition: color 0.3s;
}
.metric-value.safe  { color: var(--green); }
.metric-value.warn  { color: var(--yellow); }
.metric-value.danger { color: var(--red); }
.metric-value.neutral { color: var(--text); }
.metric-label {
  font-size: 10px; font-weight: 600;
  color: var(--text-dim);
  margin-top: 5px; letter-spacing: 0.8px;
  text-transform: uppercase;
}

/* ═══════════════════════════════════════════════
   OVERRIDE CONTROLS
   ═══════════════════════════════════════════════ */
.override-section {
  margin-top: 14px; padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}
.override-title {
  font-size: 9px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 8px;
}
.override-btns {
  display: flex; gap: 6px;
}
.ov-btn {
  flex: 1;
  padding: 8px 0;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border);
  background: transparent;
  font-family: 'Inter', sans-serif;
  font-size: 12px; font-weight: 600;
  cursor: not-allowed;
  transition: var(--transition);
  opacity: 0.3;
  display: flex; align-items: center; justify-content: center; gap: 5px;
}
.ov-btn.enabled {
  opacity: 1; cursor: pointer;
}
.ov-btn.ov-red.enabled:hover    { border-color: var(--red); color: var(--red); background: var(--red-dim); }
.ov-btn.ov-yellow.enabled:hover { border-color: var(--yellow); color: var(--yellow); background: var(--yellow-dim); }
.ov-btn.ov-green.enabled:hover  { border-color: var(--green); color: var(--green); background: var(--green-dim); }
.ov-btn .ov-dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.ov-btn.ov-red .ov-dot    { background: var(--red); }
.ov-btn.ov-yellow .ov-dot { background: var(--yellow); }
.ov-btn.ov-green .ov-dot  { background: var(--green); }

/* ═══════════════════════════════════════════════
   CAMERA FEED
   ═══════════════════════════════════════════════ */
.cam-container {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
  border: 1px solid var(--border);
  aspect-ratio: 4/3;
}
.cam-container img {
  width: 100%; height: 100%;
  object-fit: cover; display: block;
}
.cam-overlay {
  position: absolute; top: 0; left: 0; right: 0;
  padding: 10px 14px;
  display: flex; justify-content: space-between; align-items: flex-start;
  background: linear-gradient(180deg, rgba(0,0,0,0.6) 0%, transparent 100%);
  pointer-events: none;
}
.cam-badge {
  display: flex; align-items: center; gap: 6px;
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(8px);
  padding: 5px 12px; border-radius: var(--radius-pill);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; font-weight: 600;
  border: 1px solid rgba(255,255,255,0.08);
}
.cam-badge.recording { color: var(--red); }
.cam-offline {
  display: none;
  position: absolute; inset: 0;
  background: var(--bg-secondary);
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 8px;
  color: var(--text-muted); font-size: 13px;
}
.cam-offline-icon { font-size: 32px; opacity: 0.3; }
.cam-offline { display: none; }

/* ═══════════════════════════════════════════════
   VIOLATIONS TABLE
   ═══════════════════════════════════════════════ */
.table-container {
  max-height: 280px;
  overflow-y: auto;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}
.table-container::-webkit-scrollbar { width: 4px; }
.table-container::-webkit-scrollbar-track { background: transparent; }
.table-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

.v-table {
  width: 100%; border-collapse: collapse;
  font-size: 12px;
}
.v-table thead { position: sticky; top: 0; z-index: 1; }
.v-table th {
  text-align: left; padding: 10px 14px;
  background: var(--bg-elevated);
  color: var(--text-dim);
  font-size: 9px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}
.v-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--text-secondary);
}
.v-table tbody tr { transition: background 0.15s; }
.v-table tbody tr:hover { background: rgba(99,179,237,0.03); }
.v-speed { color: var(--red); font-weight: 700; }
.v-empty {
  color: var(--text-dim); text-align: center;
  padding: 32px 14px !important;
  font-style: italic; font-family: 'Inter', sans-serif;
}
.v-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px; font-weight: 600;
  color: var(--text-dim);
}

/* ═══════════════════════════════════════════════
   FOOTER
   ═══════════════════════════════════════════════ */
.footer {
  text-align: center;
  padding: 24px;
  font-size: 11px;
  color: var(--text-dim);
  border-top: 1px solid var(--border-subtle);
  margin-top: 8px;
}
.footer a { color: var(--text-muted); text-decoration: none; }
.footer a:hover { color: var(--accent); }

/* ═══════════════════════════════════════════════
   RESPONSIVE
   ═══════════════════════════════════════════════ */
@media (max-width: 840px) {
  .dashboard {
    grid-template-columns: 1fr;
    padding: 14px 12px 32px;
  }
  .full-width { grid-column: 1; }
  nav { padding: 0 16px; }
  .nav-center { display: none; }
  .lane-name { font-size: 22px; }
  .mode-status { display: none; }
  .info-bar { flex-direction: column; gap: 0; }
  .info-bar .info-item { border-bottom: 1px solid var(--border-subtle); }
}

/* ═══════════════════════════════════════════════
   ANIMATIONS
   ═══════════════════════════════════════════════ */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.card { animation: fadeInUp 0.5s ease-out both; }
.card:nth-child(1) { animation-delay: 0.05s; }
.card:nth-child(2) { animation-delay: 0.1s; }
.card:nth-child(3) { animation-delay: 0.15s; }
.card:nth-child(4) { animation-delay: 0.2s; }
.card:nth-child(5) { animation-delay: 0.25s; }
.card:nth-child(6) { animation-delay: 0.3s; }
.card:nth-child(7) { animation-delay: 0.35s; }
</style>
</head>
<body>

<!-- ═══ NAVIGATION ═══ -->
<nav>
  <div class="brand">
    <div class="brand-icon">🚦</div>
    <div class="brand-text">Synnex <span>Traffic</span></div>
  </div>
  <div class="nav-center">
    <div class="nav-pill live"><div class="dot-pulse"></div> SYSTEM ONLINE</div>
    <div class="nav-pill" id="mode-pill">⚡ AUTOMATIC</div>
  </div>
  <div class="nav-right">
    <div class="clock" id="clk"></div>
  </div>
</nav>

<!-- ═══ DASHBOARD GRID ═══ -->
<div class="dashboard">

  <!-- Alert Banner -->
  <div class="alert-banner full-width" id="alert-bar">
    <div class="alert-icon">⚠</div>
    <span id="alert-txt">Speed violation detected</span>
  </div>

  <!-- Mode Control -->
  <div class="card full-width">
    <div class="card-header">
      <div class="card-title"><span class="card-dot green"></span> System Control</div>
      <span class="mode-status" id="mode-label">MODE: AUTOMATIC</span>
    </div>
    <div class="mode-controls">
      <div class="mode-btn-group">
        <button class="mode-btn active" id="btn-auto" onclick="setMode('automatic')">
          <span class="mode-indicator"></span> ⚡ Automatic
        </button>
        <button class="mode-btn" id="btn-manual" onclick="setMode('manual')">
          <span class="mode-indicator"></span> 🎮 Manual
        </button>
      </div>
      <button class="emergency-btn" onclick="allRed()">
        🛑 Emergency Stop
      </button>
    </div>
  </div>

  <!-- System Info -->
  <div class="card full-width" style="padding:0; overflow:hidden;">
    <div class="info-bar">
      <div class="info-item">
        <div class="info-label">Controller Phase</div>
        <div class="info-value" id="phase-val">initialising</div>
      </div>
      <div class="info-item">
        <div class="info-label">Active Lane</div>
        <div class="info-value" id="active-lane">—</div>
      </div>
      <div class="info-item">
        <div class="info-label">Green Duration</div>
        <div class="info-value" id="green-dur">—</div>
      </div>
      <div class="info-item">
        <div class="info-label">Phase Elapsed</div>
        <div class="info-value" id="phase-elapsed">—</div>
      </div>
      <div class="info-item">
        <div class="info-label">Last Trigger</div>
        <div class="info-value" id="trigger-val">—</div>
      </div>
    </div>
  </div>

  <!-- Lane 1 -->
  <div class="card lane-card">
    <div class="accent-bar"></div>
    <div class="card-header">
      <div class="card-title"><span class="card-dot"></span> Lane 1 — North</div>
      <span class="card-badge" id="l1-phase-badge">IDLE</span>
    </div>
    <div class="signal-display">
      <div class="traffic-light">
        <div class="light-bulb" id="l1-red"></div>
        <div class="light-bulb" id="l1-yellow"></div>
        <div class="light-bulb" id="l1-green"></div>
      </div>
      <div class="signal-info">
        <div class="lane-name">LANE 1</div>
        <div class="signal-badges">
          <span class="sig-badge red" id="l1-pill">RED</span>
          <span class="density-chip LOW" id="l1-density">LOW</span>
        </div>
      </div>
    </div>
    <div class="metrics-grid">
      <div class="metric">
        <div class="metric-value neutral" id="l1-count">0</div>
        <div class="metric-label">Total Vehicles</div>
      </div>
      <div class="metric">
        <div class="metric-value neutral" id="l1-vpm">0</div>
        <div class="metric-label">Vehicles / min</div>
      </div>
      <div class="metric">
        <div class="metric-value safe" id="l1-speed">0.0</div>
        <div class="metric-label">Max Speed km/h</div>
      </div>
      <div class="metric">
        <div class="metric-value neutral" id="l1-current">0</div>
        <div class="metric-label">In Frame Now</div>
      </div>
    </div>
    <div class="override-section">
      <div class="override-title">Manual Override</div>
      <div class="override-btns">
        <button class="ov-btn ov-red" onclick="override(1,'red')"><span class="ov-dot"></span> Red</button>
        <button class="ov-btn ov-yellow" onclick="override(1,'yellow')"><span class="ov-dot"></span> Yellow</button>
        <button class="ov-btn ov-green" onclick="override(1,'green')"><span class="ov-dot"></span> Green</button>
      </div>
    </div>
  </div>

  <!-- Lane 2 -->
  <div class="card lane-card lane-2">
    <div class="accent-bar"></div>
    <div class="card-header">
      <div class="card-title"><span class="card-dot"></span> Lane 2 — South</div>
      <span class="card-badge" id="l2-phase-badge">IDLE</span>
    </div>
    <div class="signal-display">
      <div class="traffic-light">
        <div class="light-bulb" id="l2-red"></div>
        <div class="light-bulb" id="l2-yellow"></div>
        <div class="light-bulb" id="l2-green"></div>
      </div>
      <div class="signal-info">
        <div class="lane-name">LANE 2</div>
        <div class="signal-badges">
          <span class="sig-badge red" id="l2-pill">RED</span>
          <span class="density-chip LOW" id="l2-density">LOW</span>
        </div>
      </div>
    </div>
    <div class="metrics-grid">
      <div class="metric">
        <div class="metric-value neutral" id="l2-count">0</div>
        <div class="metric-label">Total Vehicles</div>
      </div>
      <div class="metric">
        <div class="metric-value neutral" id="l2-vpm">0</div>
        <div class="metric-label">Vehicles / min</div>
      </div>
      <div class="metric">
        <div class="metric-value safe" id="l2-speed">0.0</div>
        <div class="metric-label">Max Speed km/h</div>
      </div>
      <div class="metric">
        <div class="metric-value neutral" id="l2-current">0</div>
        <div class="metric-label">In Frame Now</div>
      </div>
    </div>
    <div class="override-section">
      <div class="override-title">Manual Override</div>
      <div class="override-btns">
        <button class="ov-btn ov-red" onclick="override(2,'red')"><span class="ov-dot"></span> Red</button>
        <button class="ov-btn ov-yellow" onclick="override(2,'yellow')"><span class="ov-dot"></span> Yellow</button>
        <button class="ov-btn ov-green" onclick="override(2,'green')"><span class="ov-dot"></span> Green</button>
      </div>
    </div>
  </div>

  <!-- Camera Feed -->
  <div class="card full-width">
    <div class="card-header">
      <div class="card-title"><span class="card-dot green"></span> Live Camera Feed</div>
      <span class="card-badge">640 × 480</span>
    </div>
    <div class="cam-container">
      <img id="cam" src="/stream" alt="Live Traffic Camera Feed"
           onerror="camErr()" onload="camOk()"/>
      <div class="cam-overlay">
        <div class="cam-badge recording"><div class="dot-pulse" style="background:var(--red);box-shadow:0 0 8px var(--red)"></div> REC</div>
        <div class="cam-badge">TRAFFIC CAM 01</div>
      </div>
      <div class="cam-offline" id="cam-offline">
        <div class="cam-offline-icon">📷</div>
        <span>Camera offline — reconnecting...</span>
      </div>
    </div>
  </div>

  <!-- Speed Violations -->
  <div class="card full-width">
    <div class="card-header">
      <div class="card-title"><span class="card-dot red"></span> Speed Violations</div>
      <span class="v-count" id="v-total">0 records</span>
    </div>
    <div class="table-container">
      <table class="v-table">
        <thead>
          <tr>
            <th style="width:40%">Timestamp</th>
            <th style="width:30%">Detected Speed</th>
            <th style="width:30%">Speed Limit</th>
          </tr>
        </thead>
        <tbody id="v-body">
          <tr><td class="v-empty" colspan="3">No speed violations recorded yet</td></tr>
        </tbody>
      </table>
    </div>
  </div>

</div>

<!-- Footer -->
<div class="footer">
  Synnex Smart Traffic Management System · Raspberry Pi Zero 2W ·
  <a href="/api/state" target="_blank">API</a> ·
  <a href="/api/pins" target="_blank">GPIO Map</a>
</div>

<!-- ═══════════════════════════════════════════════
     JAVASCRIPT
     ═══════════════════════════════════════════════ -->
<script>
(function() {
  'use strict';

  // ── Clock ──────────────────────────────────
  function updateClock() {
    const now = new Date();
    const t = now.toLocaleTimeString('en-US', {hour12:false});
    const d = now.toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});
    document.getElementById('clk').textContent = d + '  ' + t;
  }
  updateClock();
  setInterval(updateClock, 1000);

  // ── Camera recovery ────────────────────────
  window.camOk = function() {
    document.getElementById('cam').style.display = 'block';
    document.getElementById('cam-offline').style.display = 'none';
  };
  window.camErr = function() {
    document.getElementById('cam').style.display = 'none';
    document.getElementById('cam-offline').style.display = 'flex';
    setTimeout(() => {
      document.getElementById('cam').src = '/stream?t=' + Date.now();
    }, 4000);
  };

  // ── Set traffic light ──────────────────────
  function setLight(n, color) {
    ['red', 'yellow', 'green'].forEach(c => {
      const el = document.getElementById('l' + n + '-' + c);
      el.className = 'light-bulb' + (c === color ? ' on-' + c : '');
    });
    const pill = document.getElementById('l' + n + '-pill');
    pill.textContent = color.toUpperCase();
    pill.className = 'sig-badge ' + color;
  }

  // ── Speed class ────────────────────────────
  function speedClass(v) {
    if (v > 40) return 'danger';
    if (v > 20) return 'warn';
    return 'safe';
  }

  // ── Update override buttons ────────────────
  function updateOverrides(manual) {
    document.querySelectorAll('.ov-btn').forEach(btn => {
      if (manual) {
        btn.classList.add('enabled');
      } else {
        btn.classList.remove('enabled');
      }
    });
  }

  // ── API calls ──────────────────────────────
  window.setMode = function(mode) {
    fetch('/api/mode', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: mode})
    }).catch(() => {});
  };

  window.override = function(lane, color) {
    fetch('/api/override', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lane: lane, color: color})
    }).catch(() => {});
  };

  window.allRed = function() {
    fetch('/api/all_red', {method: 'POST'}).catch(() => {});
  };

  // ── Main poll ──────────────────────────────
  function poll() {
    fetch('/api/state')
      .then(r => r.json())
      .then(d => {
        const ctrl = d.controller;
        const isManual = ctrl.mode === 'manual';

        // Mode buttons
        document.getElementById('btn-auto').classList.toggle('active', !isManual);
        document.getElementById('btn-manual').classList.toggle('active', isManual);
        document.getElementById('mode-label').textContent = 'MODE: ' + ctrl.mode.toUpperCase();
        document.getElementById('mode-pill').textContent = (isManual ? '🎮' : '⚡') + ' ' + ctrl.mode.toUpperCase();
        document.getElementById('mode-pill').style.borderColor =
          isManual ? 'rgba(254,211,48,0.2)' : 'rgba(255,255,255,0.05)';
        document.getElementById('mode-pill').style.color =
          isManual ? 'var(--yellow)' : 'var(--text-secondary)';
        updateOverrides(isManual);

        // System info bar
        document.getElementById('phase-val').textContent = ctrl.phase || '—';
        document.getElementById('active-lane').textContent = 'Lane ' + ctrl.current_lane;
        document.getElementById('green-dur').textContent = ctrl.green_duration + 's';
        document.getElementById('phase-elapsed').textContent =
          (ctrl.phase_elapsed || 0).toFixed(1) + 's';
        document.getElementById('trigger-val').textContent = ctrl.last_trigger || '—';

        // Per-lane data
        [1, 2].forEach(n => {
          const lane = d.lanes[n];
          const sig = ctrl.signals[n];

          setLight(n, sig);

          // Phase badge
          const pBadge = document.getElementById('l' + n + '-phase-badge');
          if (sig === 'green') { pBadge.textContent = 'ACTIVE'; pBadge.style.color = 'var(--green)'; }
          else if (sig === 'yellow') { pBadge.textContent = 'WARN'; pBadge.style.color = 'var(--yellow)'; }
          else { pBadge.textContent = 'STOPPED'; pBadge.style.color = 'var(--text-dim)'; }

          // Metrics
          document.getElementById('l' + n + '-count').textContent = lane.count;
          document.getElementById('l' + n + '-vpm').textContent = lane.per_min;
          document.getElementById('l' + n + '-current').textContent = lane.current;

          // Density
          const db = document.getElementById('l' + n + '-density');
          db.textContent = lane.density;
          db.className = 'density-chip ' + lane.density;
        });

        // Speed (shared across lanes for now)
        const maxSpd = d.speed ? d.speed.max_speed : 0;
        [1, 2].forEach(n => {
          const sv = document.getElementById('l' + n + '-speed');
          sv.textContent = maxSpd.toFixed(1);
          sv.className = 'metric-value ' + speedClass(maxSpd);
        });

        // Violations table
        const violations = d.violations || [];
        const tbody = document.getElementById('v-body');
        document.getElementById('v-total').textContent = violations.length + ' record' + (violations.length !== 1 ? 's' : '');

        if (violations.length === 0) {
          tbody.innerHTML = '<tr><td class="v-empty" colspan="3">No speed violations recorded yet</td></tr>';
        } else {
          let rows = '';
          violations.slice(0, 20).forEach(v => {
            rows += '<tr>'
              + '<td>' + (v.timestamp || '—') + '</td>'
              + '<td class="v-speed">' + (v.speed_kmph || 0).toFixed(1) + ' km/h</td>'
              + '<td>' + (v.limit_kmph || 40) + ' km/h</td>'
              + '</tr>';
          });
          tbody.innerHTML = rows;
        }

        // Alert banner
        const ab = document.getElementById('alert-bar');
        if (maxSpd > 40) {
          ab.style.display = 'flex';
          document.getElementById('alert-txt').textContent =
            'Speed violation detected — ' + maxSpd.toFixed(1) + ' km/h (limit: 40 km/h)';
        } else {
          ab.style.display = 'none';
        }
      })
      .catch(() => {});
  }

  // Initial poll + interval
  poll();
  setInterval(poll, 1000);

})();
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template_string(PAGE)


@app.route("/stream")
def stream():
    """MJPEG live camera stream."""
    return Response(
        mjpeg_generator(camera),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/api/state")
def api_state():
    """
    JSON API: full system state.
    Consumed by the dashboard JS poll() function.
    """
    lane_data = {}
    for lid in [1, 2]:
        lane_data[lid] = detector.get_lane_data(lid)

    state = {
        "controller": controller.get_state(),
        "lanes": lane_data,
        "speed": {
            "max_speed": speed_det.get_max_speed() if speed_det else 0.0,
            "objects":   speed_det.get_speeds() if speed_det else {},
        },
        "violations": speed_det.get_violations(20) if speed_det else [],
    }
    return jsonify(state)


@app.route("/api/mode", methods=["POST"])
def api_mode():
    """Switch between automatic and manual mode."""
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "automatic")
    controller.mode = mode
    return jsonify({"status": "ok", "mode": controller.mode})


@app.route("/api/override", methods=["POST"])
def api_override():
    """Manual override: set a specific lane's light color."""
    data = request.get_json(silent=True) or {}
    lane = data.get("lane")
    color = data.get("color")

    if not lane or not color:
        return jsonify({"status": "error", "msg": "lane and color required"}), 400

    ok = controller.set_manual_light(int(lane), color)
    if ok:
        if data_logger:
            data_logger.log_signal_change(int(lane), color, "manual override")
        return jsonify({"status": "ok"})
    else:
        return jsonify({"status": "error", "msg": "not in manual mode"}), 400


@app.route("/api/all_red", methods=["POST"])
def api_all_red():
    """Emergency: set all lights to RED."""
    controller.set_all_red()
    return jsonify({"status": "ok"})


@app.route("/api/pins")
def api_pins():
    """Return GPIO pin mapping."""
    return jsonify(get_pin_info())


@app.route("/api/violations")
def api_violations():
    """Return speed violations from database."""
    if data_logger:
        return jsonify(data_logger.get_recent_violations(50))
    return jsonify([])


@app.route("/api/stats")
def api_stats():
    """Return aggregate statistics."""
    if data_logger:
        return jsonify(data_logger.get_stats_summary())
    return jsonify({})
