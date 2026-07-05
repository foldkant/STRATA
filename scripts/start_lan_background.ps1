$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$Out = Join-Path $LogDir "runserver.out.log"
$Err = Join-Path $LogDir "runserver.err.log"
if (Test-Path $Out) { Clear-Content $Out }
if (Test-Path $Err) { Clear-Content $Err }

Start-Process `
  -FilePath $Python `
  -ArgumentList @("-m", "waitress", "--listen=0.0.0.0:8000", "--threads=8", "config.wsgi:application") `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $Out `
  -RedirectStandardError $Err
