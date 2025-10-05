#!/usr/bin/env bash
# ================================================================
# UTFW Environment Bootstrap (Linux/macOS, Python version agnostic)
#
# Usage:
#   ./setup_utfw_env.sh [REPO_DIR] [PYTHON_CMD]
#
# Examples:
#   ./setup_utfw_env.sh                                  (uses script folder as REPO_DIR, python3)
#   ./setup_utfw_env.sh "/path/to/SW_Universal-Test-Framework"  (python3)
#   ./setup_utfw_env.sh "/path/to/repo" python3.12       (explicit Python 3.12)
#
# What it does:
#   - pip editable-installs UTFW from REPO_DIR
#   - installs dependencies from requirements.txt
#   - verifies the import
#   - ensures tshark/wireshark is available
# ================================================================

set -e  # Exit on error

# --- Colors for output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# --- Defaults ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${1:-$SCRIPT_DIR}"
PYTHON_CMD="${2:-python3}"

# --- Validate repo path ---
if [ ! -f "$REPO_DIR/UTFW/__init__.py" ]; then
    error "UTFW repo not found at: $REPO_DIR"
    error "Pass the correct path as the first argument."
    exit 1
fi

# --- Check Python ---
if ! command -v "$PYTHON_CMD" &> /dev/null; then
    error "Python command '$PYTHON_CMD' not found."
    error "Install Python 3 or specify a different command as the second argument."
    exit 1
fi

info "Using Python interpreter: $PYTHON_CMD"
$PYTHON_CMD --version

# --- Upgrade pip/setuptools/wheel ---
info "Upgrading pip, setuptools, wheel..."
$PYTHON_CMD -m pip install --upgrade pip setuptools wheel

# --- Install dependencies from requirements.txt ---
info "Installing dependencies from requirements.txt..."
if [ -f "$REPO_DIR/requirements.txt" ]; then
    if $PYTHON_CMD -m pip install -r "$REPO_DIR/requirements.txt"; then
        success "Dependencies installed successfully"
    else
        warn "Some dependencies from requirements.txt failed to install."
        warn "The framework may still work, but some features might be unavailable."
    fi
else
    warn "requirements.txt not found in $REPO_DIR"
fi

# --- Editable install of UTFW ---
info "Installing UTFW in editable mode from:"
info "  $REPO_DIR"
$PYTHON_CMD -m pip install -e "$REPO_DIR"

# --- Verify import ---
info "Verifying import..."
$PYTHON_CMD -c "import UTFW; print('UTFW module location:', UTFW.__file__)"

echo ""
success "UTFW is installed and importable."
info "  Interpreter: $PYTHON_CMD"
echo ""

# ================================================================
# Ensure tshark/wireshark availability
# ================================================================

ensure_tshark() {
    if command -v tshark &> /dev/null; then
        TSHARK_PATH=$(which tshark)
        success "tshark found: $TSHARK_PATH"
        return 0
    fi

    warn "tshark was not found in PATH."

    # Detect OS
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        info "Detected Linux system"

        # Check if apt-get is available (Debian/Ubuntu)
        if command -v apt-get &> /dev/null; then
            info "Debian/Ubuntu detected. You can install Wireshark/tshark with:"
            echo "  sudo apt-get update"
            echo "  sudo apt-get install -y tshark"
            echo ""
            read -p "Install tshark now? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                sudo apt-get update
                sudo apt-get install -y tshark

                # Configure tshark for non-root capture
                info "Configuring tshark for non-root packet capture..."
                sudo dpkg-reconfigure wireshark-common
                sudo usermod -aG wireshark $USER
                warn "You may need to log out and back in for group changes to take effect."
            fi
        # Check if yum is available (RHEL/CentOS/Fedora)
        elif command -v yum &> /dev/null; then
            info "RHEL/CentOS/Fedora detected. You can install Wireshark/tshark with:"
            echo "  sudo yum install -y wireshark"
            echo ""
            read -p "Install tshark now? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                sudo yum install -y wireshark
            fi
        # Check if pacman is available (Arch Linux)
        elif command -v pacman &> /dev/null; then
            info "Arch Linux detected. You can install Wireshark/tshark with:"
            echo "  sudo pacman -S wireshark-cli"
            echo ""
            read -p "Install tshark now? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                sudo pacman -S wireshark-cli
            fi
        else
            warn "Could not detect package manager. Please install Wireshark/tshark manually."
        fi

    elif [[ "$OSTYPE" == "darwin"* ]]; then
        info "Detected macOS system"

        # Check if brew is available
        if command -v brew &> /dev/null; then
            info "Homebrew detected. You can install Wireshark/tshark with:"
            echo "  brew install wireshark"
            echo ""
            read -p "Install tshark via Homebrew now? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                brew install wireshark
            fi
        else
            warn "Homebrew not found. Install it from https://brew.sh/ then run:"
            echo "  brew install wireshark"
        fi
    else
        warn "Unknown operating system: $OSTYPE"
        warn "Please install Wireshark/tshark manually."
    fi

    # Check again if tshark is now available
    if command -v tshark &> /dev/null; then
        success "tshark is now available!"
        return 0
    else
        warn "tshark is still not available. Some PCAP-related tests may not work."
        warn "Install Wireshark and ensure tshark is in your PATH."
        return 1
    fi
}

ensure_tshark

echo ""
success "Environment bootstrap complete."
info "You can now run your UTFW testcases."
echo ""
