param([int]$Port = 0)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Uvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"
$WorkerLauncher = Join-Path $PSScriptRoot "start_curriculum_ocr_worker.ps1"
$AppWorkerLauncher = Join-Path $PSScriptRoot "start_app_worker.ps1"
if ($Port -le 0) {
  $Port = if ($env:STRATA_PORT) { [int]$env:STRATA_PORT } else { 8010 }
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $WorkerLauncher -BrokerMode Auto -CpuCount 1
if ($LASTEXITCODE -ne 0) {
  throw "The curriculum-standard background worker could not be started."
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $AppWorkerLauncher
if ($LASTEXITCODE -ne 0) {
  throw "The application background worker could not be started."
}
& $Uvicorn "config.asgi:application" --host 127.0.0.1 --port $Port
