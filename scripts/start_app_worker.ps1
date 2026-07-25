param([int]$StartupTimeoutSeconds = 20)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$Runner = Join-Path $PSScriptRoot "run_celery_worker.ps1"
$LogDir = Join-Path $Root "logs\app_worker"
$OutLog = Join-Path $LogDir "worker.out.log"
$ErrLog = Join-Path $LogDir "worker.err.log"
$QueueName = if ($env:AI_GENERATION_QUEUE) { $env:AI_GENERATION_QUEUE.Trim() } else { "ai_generation" }
if (-not $QueueName) { $QueueName = "ai_generation" }
$QueueMarker = "--queues=celery,$QueueName"

function Find-AppWorker {
  return @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        $_.CommandLine -and
        $_.CommandLine.Contains("-A config worker") -and
        $_.CommandLine.Contains($QueueMarker)
      }
  )
}

$Existing = Find-AppWorker
if ($Existing.Count -gt 0) {
  Write-Host "Application background worker is already running (PID $($Existing[0].ProcessId))."
  exit 0
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Start-Process `
  -FilePath "powershell.exe" `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Runner) `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $OutLog `
  -RedirectStandardError $ErrLog

$Deadline = (Get-Date).AddSeconds([Math]::Max($StartupTimeoutSeconds, 3))
do {
  Start-Sleep -Milliseconds 500
  $Started = Find-AppWorker
  if ($Started.Count -gt 0) {
    Write-Host "Application background worker started (PID $($Started[0].ProcessId)); queues: celery,$QueueName."
    exit 0
  }
} while ((Get-Date) -lt $Deadline)

if (Test-Path $ErrLog) {
  Get-Content -LiteralPath $ErrLog -Tail 20
}
throw "Application background worker did not start within $StartupTimeoutSeconds seconds."
