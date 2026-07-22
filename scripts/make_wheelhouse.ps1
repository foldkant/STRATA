$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Wheelhouse = Join-Path $Root "wheelhouse"
New-Item -ItemType Directory -Force $Wheelhouse | Out-Null
& $Python -m pip download -r (Join-Path $Root "requirements\base.txt") -d $Wheelhouse
& $Python -m pip download -r (Join-Path $Root "requirements\dev.txt") -d $Wheelhouse
& $Python -m pip download -r (Join-Path $Root "requirements\ai.txt") -d $Wheelhouse
& $Python -m pip download -r (Join-Path $Root "requirements\curriculum.txt") -d $Wheelhouse
Write-Host "Wheelhouse created at $Wheelhouse"
