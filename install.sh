#!/bin/bash
# =============================================
# SmartRail Traffic System — Setup Script
# Raspberry Pi Zero 2W | Raspberry Pi OS 64-bit
# Run once as: sudo bash install.sh
# =============================================
set -e

PROJ="/home/pi/smartrail"
VENV="$PROJ/venv"
SVC="smartrail"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║     SmartRail Traffic System        ║"
echo "╚══════════════════════════════════════╝"
echo ""

echo "▶ [1/6] Installing system packages..."
apt-get update -y
apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    python3-picamera2 python3-libcamera \
    python3-opencv i2c-tools \
    libatlas-base-dev libjpeg-dev \
    libopencv-dev libgpiod2

echo "▶ [2/6] Enabling I2C and Camera..."
raspi-config nonint do_i2c    0
raspi-config nonint do_camera 0
grep -q "i2c-dev" /etc/modules || echo "i2c-dev" >> /etc/modules
modprobe i2c-dev 2>/dev/null || true

echo "▶ [3/6] Project directory → $PROJ"
mkdir -p "$PROJ"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
for f in traffic_system.py README.md; do
    [ -f "$SCRIPT_DIR/$f" ] && cp "$SCRIPT_DIR/$f" "$PROJ/" && echo "   copied $f"
done
chown -R pi:pi "$PROJ"

echo "▶ [4/6] Creating Python venv..."
sudo -u pi python3 -m venv --system-site-packages "$VENV"
sudo -u pi "$VENV/bin/pip" install --upgrade pip wheel
for pkg in flask "RPi.GPIO" VL53L0X smbus2; do
    echo "   → $pkg"
    sudo -u pi "$VENV/bin/pip" install "$pkg" || echo "   WARN: $pkg failed"
done
sudo -u pi "$VENV/bin/python" -c "import flask;     print('   OK flask')"
sudo -u pi "$VENV/bin/python" -c "import RPi.GPIO;  print('   OK RPi.GPIO')"
sudo -u pi "$VENV/bin/python" -c "import cv2;        print('   OK cv2')"
sudo -u pi "$VENV/bin/python" -c "import picamera2;  print('   OK picamera2')" 2>/dev/null || echo "   WARN picamera2"
sudo -u pi "$VENV/bin/pip" freeze > "$PROJ/requirements.txt"

echo "▶ [5/6] Creating systemd service..."
cat > /etc/systemd/system/${SVC}.service <<EOF
[Unit]
Description=SmartRail Traffic Control System
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=${PROJ}
ExecStart=${VENV}/bin/python ${PROJ}/traffic_system.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SVC}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SVC}.service

echo "▶ [6/6] Starting service..."
systemctl start ${SVC}.service

PI_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "╔══════════════════════════════════════╗"
echo "║           All done!                 ║"
echo "╚══════════════════════════════════════╝"
echo "  Open → http://${PI_IP}:5000"
echo "  sudo journalctl -u ${SVC} -f   <- live logs"
echo ""
