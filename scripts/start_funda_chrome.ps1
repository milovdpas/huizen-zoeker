# LEGACY — only needed for `refresh_funda_cookies.ps1 --use-system-browser`.
# The default refresh path now uses a self-contained Playwright session and
# does NOT need this script at all.
#
# Launches a dedicated Chrome instance with --remote-debugging-port=9222 +
# its own --user-data-dir, so refresh_funda_cookies.ps1 --use-system-browser
# can read cookies via CDP. We use a separate profile because Chrome 136+
# refuses the debug port on the default profile for security reasons.
#
# This dedicated Chrome runs ALONGSIDE your main Chrome (separate process,
# separate cookies). Sign into funda once in this window; the profile is
# persisted under %LOCALAPPDATA%\huizen-zoeker-chrome-profile so subsequent
# runs reuse the same session.

$ErrorActionPreference = "Stop"

$chromePaths = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Error "chrome.exe not found."
    exit 1
}

# If port is already listening, nothing to do.
$alreadyListening = Test-NetConnection -ComputerName localhost -Port 9222 `
    -WarningAction SilentlyContinue -InformationLevel Quiet
if ($alreadyListening) {
    Write-Host "Chrome already listening on :9222 - nothing to do."
    exit 0
}

$profileDir = Join-Path $env:LOCALAPPDATA "huizen-zoeker-chrome-profile"
if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir | Out-Null
    Write-Host "Created dedicated profile at $profileDir"
}

$fundaUrl = 'https://www.funda.nl/zoeken/huur/?selected_area=["oss"]'
Write-Host "Launching dedicated Chrome with --remote-debugging-port=9222 ..."
Start-Process $chrome -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$profileDir",
    $fundaUrl
) | Out-Null

Write-Host "Waiting for Chrome to listen on :9222 ..."
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    $tcp = Test-NetConnection -ComputerName localhost -Port 9222 `
        -WarningAction SilentlyContinue -InformationLevel Quiet
    if ($tcp) { $ok = $true; break }
}

if ($ok) {
    Write-Host "OK - Chrome is listening on :9222."
    Write-Host ""
    Write-Host "First time only: in the Chrome window that just opened, wait for"
    Write-Host "funda.nl to render past any 'Je bent bijna op de pagina' check."
    Write-Host "Then run: .\scripts\refresh_funda_cookies.ps1"
} else {
    Write-Warning "Chrome did not start listening on :9222 within 20s."
    exit 2
}
