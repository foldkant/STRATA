$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root ".env"
if (!(Test-Path $EnvPath)) {
  Copy-Item (Join-Path $Root ".env.example") $EnvPath
}

$content = Get-Content $EnvPath -Raw
$content = $content -replace "DATABASE_ENGINE=sqlite", "DATABASE_ENGINE=postgresql"
$content = $content -replace "DATABASE_NAME=storage/dev.sqlite3", "DATABASE_NAME=xlzxedu"
Set-Content -Encoding UTF8 $EnvPath $content

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python (Join-Path $Root "manage.py") migrate
Write-Host "Switched to PostgreSQL settings and applied migrations."
