#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Synnex Smart Traffic Management System — Installer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  Usage:  sudo bash install.sh
#
#  Designed for Raspberry Pi Zero 2W running Raspberry Pi OS (64-bit)
#
#  What this does:
#    1. Enables camera interface
#    2. Installs system packages (OpenCV, picamera2)
#    3. Creates Python venv with system site-packages
#    4. Installs pip dependencies (Flask, RPi.GPIO, numpy)
#    5. Registers & starts a systemd service
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$INSTALL_DIR/venv"
SERVICE_NAME="synnex-traffic"
USER_NAME="${SUDO_USER:-pi}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚦 Synnex Traffic System — Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Install dir : $INSTALL_DIR"
echo "  User        : $USER_NAME"
echo "  Venv        : $VENV_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Check root ───────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "❌ Please run as root: sudo bash install.sh"
    exit 1
fi

# ── 1. Enable camera ────────────────────────────
echo ""
echo "📷 Enabling camera interface..."
if command -v raspi-config &> /dev/null; then
    raspi-config nonint do_camera 0 2>/dev/null || true
    # Also enable via config.txt for legacy support
    if ! grep -q "start_x=1" /boot/config.txt 2>/dev/null; then
        echo "start_x=1" >> /boot/config.txt
    fi
    if ! grep -q "gpu_mem=" /boot/config.txt 2>/dev/null; then
        echo "gpu_mem=128" >> /boot/config.txt
    fi
    echo "  ✓ Camera interface enabled"
else
    echo "  ⚠ raspi-config not found (not on Pi?) — skipping"
fi

# ── 2. System packages ──────────────────────────
echo ""
echo "📦 Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3-venv \
    python3-pip \
    python3-picamera2 \
    python3-opencv \
    python3-numpy \
    libatlas-base-dev \
    libopenjp2-7 \
    libtiff5 \
    2>/dev/null
echo "  ✓ System packages installed"

# ── 3. Python venv ──────────────────────────────
echo ""
echo "🐍 Creating Python virtual environment..."
if [[ -d "$VENV_DIR" ]]; then
    echo "  ⚠ Existing venv found — removing"
    rm -rf "$VENV_DIR"
fi
# --system-site-packages lets us use apt-installed picamera2 + opencv
python3 -m venv "$VENV_DIR" --system-site-packages
echo "  ✓ Venv created at $VENV_DIR"

# ── 4. Pip packages ─────────────────────────────
echo ""
echo "📥 Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install \
    flask>=2.3.0 \
    RPi.GPIO>=0.7.1 \
    numpy>=1.24.0 \
    --quiet
echo "  ✓ pip packages installed"

# ── 5. Set ownership ────────────────────────────
chown -R "$USER_NAME:$USER_NAME" "$INSTALL_DIR"

# ── 6. Systemd service ──────────────────────────
echo ""
echo "⚙️  Setting up systemd service..."

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Synnex Smart Traffic Management System
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Resource limits for Pi Zero 2W
MemoryMax=256M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
echo "  ✓ Service '$SERVICE_NAME' enabled and started"

# ── Done ─────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Installation complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Dashboard : http://${IP:-<PI_IP>}:5000"
echo "  Stream    : http://${IP:-<PI_IP>}:5000/stream"
echo "  API       : http://${IP:-<PI_IP>}:5000/api/state"
echo ""
echo "  Service commands:"
echo "    sudo systemctl status  $SERVICE_NAME"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "    sudo systemctl stop    $SERVICE_NAME"
echo "    sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "  Manual run (for testing):"
echo "    source $VENV_DIR/bin/activate"
echo "    python main.py"
echo ""
echo "  ⚠ If this is a first-time install, reboot to enable camera:"
echo "    sudo reboot"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"