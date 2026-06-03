# Manual cookie refresh - launches Playwright's own Chromium, navigates funda,
# accepts the cookie banner, and reads cookies straight from the browser
# context (no admin / no decryption needed). Writes cookies/funda.txt.
#
# Usage:
#   .\scripts\refresh_funda_cookies.ps1
#   .\scripts\refresh_funda_cookies.ps1 --headless           # no visible window
#   .\scripts\refresh_funda_cookies.ps1 --wait=45            # longer settle time
#   .\scripts\refresh_funda_cookies.ps1 --use-system-browser # legacy: read your real browser (see start_funda_chrome.ps1)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvActivate = Join-Path $root ".venv\Scripts\Activate.ps1"
$pyScript = Join-Path $root "scripts\refresh_funda_cookies.py"

if (Test-Path $venvActivate) {
    . $venvActivate
} else {
    Write-Warning "No .venv found at $venvActivate - using system python."
}

python $pyScript @args
exit $LASTEXITCODE
