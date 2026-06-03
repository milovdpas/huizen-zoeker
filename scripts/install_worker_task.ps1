# Registers a Windows Scheduled Task that runs the huizen-zoeker scraper/notifier
# worker at user logon. Re-run this script to update an existing task.
#
# Usage (from an elevated-or-normal PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\install_worker_task.ps1
#
# To remove:  Unregister-ScheduledTask -TaskName "HuizenZoeker Worker" -Confirm:$false

$ErrorActionPreference = "Stop"

$TaskName  = "HuizenZoeker Worker"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Pythonw    = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$Script     = Join-Path $ProjectDir "run_worker.py"

if (-not (Test-Path $Pythonw)) { throw "Not found: $Pythonw" }
if (-not (Test-Path $Script))  { throw "Not found: $Script" }

$action = New-ScheduledTaskAction `
    -Execute $Pythonw `
    -Argument "`"$Script`"" `
    -WorkingDirectory $ProjectDir

# At logon of the current user. Interactive session is required because the
# funda cookie refresh job opens a Playwright browser window.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs huizen-zoeker scraper + notifier scheduler in the background." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName'."
Write-Host "  Runs:    $Pythonw `"$Script`""
Write-Host "  Trigger: at logon of $env:USERNAME"
Write-Host "  Logs:    $ProjectDir\logs\worker.log"
Write-Host ""
Write-Host "Start now with:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check status:    Get-ScheduledTaskInfo -TaskName '$TaskName'"
