#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Synnex Smart Traffic Management System — Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  One-command setup for Raspberry Pi Zero 2W.
#
#  Usage:
#    cd ~/synnex
#    chmod +x setup.sh
#    sudo bash setup.sh
#
#  What this does:
#    1. Enables camera interface
#    2. Installs system packages (OpenCV, picamera2, numpy)
#    3. Creates Python venv with --system-site-packages
#    4. Installs pip dependencies (Flask, RPi.GPIO, numpy)
#    5. Verifies all imports work
#    6. Registers & starts a systemd service (auto-start on boot)
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$INSTALL_DIR/venv"
SERVICE_NAME="synnex-traffic"
USER_NAME="${SUDO_USER:-pi}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚦 Synnex Traffic System — Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Install dir : $INSTALL_DIR"
echo "  User        : $USER_NAME"
echo "  Venv        : $VENV_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Check root ───────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "❌ Please run as root: sudo bash setup.sh"
    exit 1
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Step 1: Enable camera interface
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "📷 [1/6] Enabling camera interface..."

if command -v raspi-config &> /dev/null; then
    raspi-config nonint do_camera 0 2>/dev/null || true
    # Legacy support via config.txt
    if ! grep -q "start_x=1" /boot/config.txt 2>/dev/null; then
        echo "start_x=1" >> /boot/config.txt
    fi
    if ! grep -q "gpu_mem=" /boot/config.txt 2>/dev/null; then
        echo "gpu_mem=128" >> /boot/config.txt
    fi
    echo "  ✅ Camera interface enabled"
else
    echo "  ⚠ raspi-config not found (not on Pi?) — skipping"
fi
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Step 2: Install system packages
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "📦 [2/6] Installing system packages..."

apt-get update -qq
apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-picamera2 \
    python3-opencv \
    python3-numpy \
    libatlas-base-dev \
    libopenjp2-7 \
    libtiff5 \
    2>/dev/null

echo "  ✅ System packages installed"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Step 3: Create Python virtual environment
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "🐍 [3/6] Creating Python virtual environment..."

if [ -d "$VENV_DIR" ]; then
    echo "  ⚠ Existing venv found — removing"
    rm -rf "$VENV_DIR"
fi

# --system-site-packages is critical:
#   picamera2 and opencv are installed via apt (pre-built for ARM).
#   Building from source on Pi Zero 2W takes hours and often fails.
python3 -m venv "$VENV_DIR" --system-site-packages

echo "  ✅ Venv created at: $VENV_DIR"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Step 4: Install pip dependencies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "📥 [4/6] Installing pip dependencies..."

"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install \
    flask>=2.3.0 \
    RPi.GPIO>=0.7.1 \
    numpy>=1.24.0 \
    --quiet

echo "  ✅ pip packages installed"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Step 5: Verify all imports
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "🔍 [5/6] Verifying imports..."
echo ""

"$VENV_DIR/bin/python" -c "
import sys
print(f'  Python  : {sys.version}')

modules = {
    'flask':     'Flask web framework',
    'cv2':       'OpenCV (computer vision)',
    'numpy':     'NumPy (array operations)',
}

# Optional: RPi.GPIO (may fail if not on Pi hardware)
try:
    import RPi.GPIO
    print(f'  RPi.GPIO  : ✅ {RPi.GPIO.VERSION}')
except Exception:
    print(f'  RPi.GPIO  : ⚠  Not available (will work on actual Pi)')

# Optional: picamera2
try:
    import picamera2
    print(f'  picamera2 : ✅ OK')
except ImportError:
    print(f'  picamera2 : ⚠  Not found (install: sudo apt install python3-picamera2)')

for mod, desc in modules.items():
    try:
        m = __import__(mod)
        ver = getattr(m, '__version__', 'OK')
        print(f'  {mod:12s}: ✅ {ver}')
    except ImportError as e:
        print(f'  {mod:12s}: ❌ {e}')

print()
print('  All checks complete.')
"

echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Step 6: Set up systemd service (auto-start on boot)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "⚙️  [6/6] Setting up systemd service..."

# Set file ownership
chown -R "$USER_NAME:$USER_NAME" "$INSTALL_DIR"

# Create the systemd service file
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

echo "  ✅ Service '$SERVICE_NAME' enabled and started"
echo "  ✅ Will auto-start on every boot"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Done
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IP=$(hostname -I | awk '{print $1}')

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Setup complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
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
echo "    cd $INSTALL_DIR"
echo "    source venv/bin/activate"
echo "    python main.py"
echo ""
echo "  ⚠ First-time install? Reboot to enable camera:"
echo "    sudo reboot"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
