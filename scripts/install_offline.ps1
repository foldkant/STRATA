$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Wheelhouse = Join-Path $Root "wheelhouse"
if (!(Test-Path $Python)) {
  py -3.12 -m venv (Join-Path $Root ".venv")
}
& $Python -m pip install --no-index --find-links $Wheelhouse -r (Join-Path $Root "requirements\base.txt")
Write-Host "Offline dependencies installed."
