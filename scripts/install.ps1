# Elara Core — one-line installer for Windows
# Usage: irm https://raw.githubusercontent.com/navigatorbuilds/elara-core/main/scripts/install.ps1 | iex
#
# What this does:
#   1. Checks for Python 3.10+
#   2. Installs elara-core[network] via pipx (preferred) or pip
#   3. Runs elara init --yes for non-interactive setup
#   4. Every install becomes a LEAF node in the Elara mesh network

$ErrorActionPreference = "Stop"

function Write-Info { Write-Host "> $args" -ForegroundColor Cyan }
function Write-Ok { Write-Host "✓ $args" -ForegroundColor Green }
function Write-Warn { Write-Host "! $args" -ForegroundColor Yellow }
function Write-Fail {
    Write-Host "✗ $args" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  Elara Core" -NoNewline -ForegroundColor White
Write-Host " — persistent memory for AI assistants" -ForegroundColor DarkGray
Write-Host ""

# -----------------------------------------------------------------------
# 1. Check Python 3.10+
# -----------------------------------------------------------------------
$Python = $null

foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
                $Python = $cmd
                break
            }
        }
    } catch { }
}

if (-not $Python) {
    Write-Info "Python 3.10+ not found. Attempting install via winget..."

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            $Python = "python"
            Write-Ok "Python installed via winget (you may need to restart your terminal)"
        } catch {
            Write-Fail "Could not install Python. Install manually from: https://python.org/downloads/"
        }
    } else {
        Write-Fail "Python 3.10+ required. Install from: https://python.org/downloads/"
    }
}

$PyVer = & $Python --version 2>&1
Write-Ok "Python: $PyVer"

# -----------------------------------------------------------------------
# 2. Install elara-core[network]
# -----------------------------------------------------------------------
$Installed = $false

# Try pipx first
if (Get-Command pipx -ErrorAction SilentlyContinue) {
    Write-Info "Installing via pipx (recommended)..."
    try {
        pipx install "elara-core[network]" 2>$null
        $Installed = $true
        Write-Ok "Installed via pipx"
    } catch {
        try {
            pipx upgrade "elara-core[network]" 2>$null
            $Installed = $true
            Write-Ok "Upgraded via pipx"
        } catch { }
    }
}

# Fall back to pip
if (-not $Installed) {
    Write-Info "Installing via pip..."
    try {
        & $Python -m pip install "elara-core[network]" --quiet
        $Installed = $true
        Write-Ok "Installed via pip"
    } catch {
        Write-Fail "Installation failed. Try: $Python -m pip install elara-core[network]"
    }
}

# -----------------------------------------------------------------------
# 3. Verify
# -----------------------------------------------------------------------
if (-not (Get-Command elara -ErrorAction SilentlyContinue)) {
    Write-Warn "elara installed but not in PATH. Try restarting your terminal."
    # Try via python -m
    & $Python -m elara_mcp.cli init --yes 2>$null
} else {
    Write-Ok "elara installed"

    # -----------------------------------------------------------------------
    # 4. Initialize
    # -----------------------------------------------------------------------
    Write-Info "Initializing Elara..."
    elara init --yes
}

Write-Host ""
Write-Host "  Ready!" -ForegroundColor White
Write-Host ""
Write-Host "  Your Elara instance is a LEAF node in the mesh network." -ForegroundColor DarkGray
Write-Host "  It shares anonymized validation records — no personal data." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Connect to your AI client:"
Write-Host "       claude mcp add elara -- elara serve" -ForegroundColor Cyan
Write-Host ""
Write-Host "    2. Or start the server directly:"
Write-Host "       elara serve" -ForegroundColor Cyan
Write-Host ""
Write-Host "    3. Manage your node:"
Write-Host "       elara node status" -NoNewline -ForegroundColor Cyan
Write-Host "    — check node info"
Write-Host "       elara node stop" -NoNewline -ForegroundColor Cyan
Write-Host "      — opt out of network"
Write-Host ""
Write-Host "  Docs: https://elara.navigatorbuilds.com" -ForegroundColor DarkGray
Write-Host ""
