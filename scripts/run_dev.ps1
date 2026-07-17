param([int]$Port = 0)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Uvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"
if ($Port -le 0) {
  $Port = if ($env:STRATA_PORT) { [int]$env:STRATA_PORT } else { 8010 }
}
& $Uvicorn "config.asgi:application" --host 127.0.0.1 --port $Port
