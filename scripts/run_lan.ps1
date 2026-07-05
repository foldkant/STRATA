$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python (Join-Path $Root "manage.py") runserver 0.0.0.0:8000 --noreload
