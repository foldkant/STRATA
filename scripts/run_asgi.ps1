$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Uvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"
& $Uvicorn "config.asgi:application" --host 0.0.0.0 --port 8000
