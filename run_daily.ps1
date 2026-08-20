# Runs the daily digest pipeline and refreshes out\index.html
# Invoked by Windows Task Scheduler (see setup_task.ps1).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$logDir = Join-Path $root 'data'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'run.log'

"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Add-Content $log
& $python -m daily_digest.cli concepts --quiet 2>&1 | Tee-Object -Append $log
& $python -m daily_digest.cli run 2>&1 | Tee-Object -Append $log

if ($args -contains '-Open') {
    Start-Process (Join-Path $root 'out\index.html')
}
