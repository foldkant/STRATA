$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Wheelhouse = Join-Path $Root "wheelhouse"
if (!(Test-Path $Python)) {
  py -3.12 -m venv (Join-Path $Root ".venv")
}
& $Python -m pip install --no-index --find-links $Wheelhouse -r (Join-Path $Root "requirements\base.txt")
& $Python -m pip install --no-index --find-links $Wheelhouse -r (Join-Path $Root "requirements\curriculum.txt")
& $Python -m pip check
& $Python -c "import fitz, pypdf, rapidocr_onnxruntime; print('Curriculum document dependencies verified.')"
if ($env:OS -eq "Windows_NT") {
  & $Python -c "import pywintypes, win32file; print('Windows filesystem broker dependency verified.')"
}
Write-Host "Offline dependencies installed."
