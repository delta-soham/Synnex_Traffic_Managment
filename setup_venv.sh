#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Synnex — Raspberry Pi Virtual Environment Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  Run this ON the Raspberry Pi:
#    cd ~/synnex
#    chmod +x setup_venv.sh
#    bash setup_venv.sh
#
#  What it does:
#    1. Installs required system packages via apt
#    2. Creates a Python venv with --system-site-packages
#       (so picamera2 + opencv from apt are accessible)
#    3. Installs pip dependencies (flask, RPi.GPIO, numpy)
#    4. Verifies all imports work
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚦 Synnex — RPi Venv Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Project : $PROJECT_DIR"
echo "  Venv    : $VENV_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─────────────────────────────────────────────────
#  Step 1: Install system packages
# ─────────────────────────────────────────────────
echo "📦 [1/4] Installing system packages..."
echo "  (requires sudo — enter password if prompted)"
echo ""

sudo apt-get update -qq

sudo apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-picamera2 \
    python3-opencv \
    python3-numpy \
    libatlas-base-dev \
    libopenjp2-7 \
    libtiff5

echo ""
echo "  ✅ System packages installed"
echo ""

# ─────────────────────────────────────────────────
#  Step 2: Create virtual environment
# ─────────────────────────────────────────────────
echo "🐍 [2/4] Creating virtual environment..."

# Remove existing venv if present
if [ -d "$VENV_DIR" ]; then
    echo "  ⚠ Existing venv found — removing it"
    rm -rf "$VENV_DIR"
fi

# --system-site-packages is CRITICAL on RPi:
#   picamera2 and opencv are installed via apt (pre-built for ARM).
#   Building them from source on Pi Zero 2W takes hours and often fails.
#   This flag lets the venv access those apt-installed packages.
python3 -m venv "$VENV_DIR" --system-site-packages

echo "  ✅ Venv created at: $VENV_DIR"
echo ""

# ─────────────────────────────────────────────────
#  Step 3: Install pip dependencies
# ─────────────────────────────────────────────────
echo "📥 [3/4] Installing pip dependencies..."

# Activate the venv
source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --upgrade pip --quiet

# Install project dependencies
pip install \
    flask>=2.3.0 \
    RPi.GPIO>=0.7.1 \
    numpy>=1.24.0 \
    --quiet

echo "  ✅ pip packages installed"
echo ""

# ─────────────────────────────────────────────────
#  Step 4: Verify all imports
# ─────────────────────────────────────────────────
echo "🔍 [4/4] Verifying imports..."
echo ""

python3 -c "
import sys
print(f'  Python  : {sys.version}')

modules = {
    'flask':     'Flask web framework',
    'cv2':       'OpenCV (computer vision)',
    'numpy':     'NumPy (array operations)',
    'RPi.GPIO':  'RPi.GPIO (GPIO control)',
}

# Optional module
try:
    import picamera2
    print(f'  picamera2 : ✅ {picamera2.__version__ if hasattr(picamera2, \"__version__\") else \"OK\"}')
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
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Venv setup complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  To activate the venv:"
echo "    source $VENV_DIR/bin/activate"
echo ""
echo "  To run the system:"
echo "    source $VENV_DIR/bin/activate"
echo "    python main.py"
echo ""
echo "  To deactivate:"
echo "    deactivate"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
