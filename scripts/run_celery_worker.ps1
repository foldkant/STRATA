$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Celery = Join-Path $Root ".venv\Scripts\celery.exe"
Set-Location $Root
& $Celery -A config worker -l info --pool=solo
