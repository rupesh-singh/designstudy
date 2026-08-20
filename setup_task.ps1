# Registers a Windows Scheduled Task that builds the digest every morning.
# Usage:  .\setup_task.ps1 [-Time 07:30] [-Remove]
param(
    [string]$Time = '07:30',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$taskName = 'DailyEngineeringDigest'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$runner = Join-Path $root 'run_daily.ps1'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$taskName'."
    return
}

if (-not (Test-Path $runner)) { throw "run_daily.ps1 not found at $runner" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Builds the daily curated engineering digest.' -Force | Out-Null

Write-Host "Scheduled task '$taskName' registered for $Time daily."
Write-Host "Digest will be written to: $(Join-Path $root 'out\index.html')"
Write-Host ""
Write-Host "Tip: set this as your browser home page ->"
Write-Host "  file:///$($root -replace '\\','/')/out/index.html"
