#!/bin/sh
# Elara Core — one-line installer for Linux and macOS
# Usage: curl -sSL https://raw.githubusercontent.com/navigatorbuilds/elara-core/main/scripts/install.sh | sh
#
# What this does:
#   1. Checks for Python 3.10+
#   2. Installs elara-core[network] via pipx (preferred) or pip
#   3. Runs elara init --yes for non-interactive setup
#   4. Every install becomes a LEAF node in the Elara mesh network

set -e

# Colors (respect NO_COLOR)
if [ -z "${NO_COLOR:-}" ] && [ -t 1 ]; then
    GREEN='\033[32m'
    RED='\033[31m'
    YELLOW='\033[33m'
    CYAN='\033[36m'
    BOLD='\033[1m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    GREEN='' RED='' YELLOW='' CYAN='' BOLD='' DIM='' RESET=''
fi

info()  { printf "${CYAN}>${RESET} %s\n" "$1"; }
ok()    { printf "${GREEN}✓${RESET} %s\n" "$1"; }
warn()  { printf "${YELLOW}!${RESET} %s\n" "$1"; }
fail()  { printf "${RED}✗${RESET} %s\n" "$1"; exit 1; }

echo ""
echo "${BOLD}  Elara Core${RESET}${DIM} — persistent memory for AI assistants${RESET}"
echo ""

# -----------------------------------------------------------------------
# 1. Detect OS
# -----------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux*)  OS_NAME="Linux" ;;
    Darwin*) OS_NAME="macOS" ;;
    *)       fail "Unsupported OS: $OS. Use Linux or macOS." ;;
esac

info "Detected: $OS_NAME ($ARCH)"

# -----------------------------------------------------------------------
# 2. Check Python 3.10+
# -----------------------------------------------------------------------
PYTHON=""

for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" = "3" ] && [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.10+ required but not found.
  Install from: https://python.org/downloads/
  macOS: brew install python@3.12
  Ubuntu/Debian: sudo apt install python3.12
  Fedora: sudo dnf install python3.12"
fi

ok "Python: $($PYTHON --version)"

# -----------------------------------------------------------------------
# 3. Install elara-core[network]
# -----------------------------------------------------------------------
INSTALLED=0

# Try pipx first (isolated environment, recommended)
if command -v pipx >/dev/null 2>&1; then
    info "Installing via pipx (recommended)..."
    if pipx install "elara-core[network]" 2>/dev/null; then
        INSTALLED=1
        ok "Installed via pipx"
    else
        # Might already be installed — try upgrade
        if pipx upgrade "elara-core[network]" 2>/dev/null; then
            INSTALLED=1
            ok "Upgraded via pipx"
        fi
    fi
fi

# Fall back to pip --user
if [ "$INSTALLED" = "0" ]; then
    if $PYTHON -m pip --version >/dev/null 2>&1; then
        info "Installing via pip..."
        $PYTHON -m pip install --user "elara-core[network]" --quiet
        INSTALLED=1
        ok "Installed via pip"
    fi
fi

if [ "$INSTALLED" = "0" ]; then
    fail "Could not install elara-core. Install pip first:
  $PYTHON -m ensurepip --upgrade"
fi

# -----------------------------------------------------------------------
# 4. Verify installation
# -----------------------------------------------------------------------
if ! command -v elara >/dev/null 2>&1; then
    # pip --user might not be in PATH
    USER_BIN="$($PYTHON -m site --user-base)/bin"
    if [ -x "$USER_BIN/elara" ]; then
        warn "elara is installed but not in PATH."
        echo "  Add to your shell config:"
        echo "    export PATH=\"$USER_BIN:\$PATH\""
        export PATH="$USER_BIN:$PATH"
    else
        fail "Installation succeeded but 'elara' command not found."
    fi
fi

ok "elara $(elara --version 2>/dev/null || echo '(installed)')"

# -----------------------------------------------------------------------
# 5. Initialize
# -----------------------------------------------------------------------
info "Initializing Elara..."
elara init --yes

echo ""
echo "${BOLD}  Ready!${RESET}"
echo ""
echo "  ${DIM}Your Elara instance is a LEAF node in the mesh network.${RESET}"
echo "  ${DIM}It shares anonymized validation records — no personal data.${RESET}"
echo ""
echo "  ${BOLD}Next steps:${RESET}"
echo "    1. Connect to your AI client:"
echo "       ${CYAN}claude mcp add elara -- elara serve${RESET}"
echo ""
echo "    2. Or start the server directly:"
echo "       ${CYAN}elara serve${RESET}"
echo ""
echo "    3. Manage your node:"
echo "       ${CYAN}elara node status${RESET}    — check node info"
echo "       ${CYAN}elara node stop${RESET}      — opt out of network"
echo ""
echo "  ${DIM}Docs: https://elara.navigatorbuilds.com${RESET}"
echo ""
