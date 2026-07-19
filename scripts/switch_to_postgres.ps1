$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root ".env"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path $EnvPath)) {
  Copy-Item (Join-Path $Root ".env.example") $EnvPath
}

$content = Get-Content $EnvPath -Raw
$content = $content -replace "DATABASE_ENGINE=sqlite", "DATABASE_ENGINE=postgresql"
$content = $content -replace "DATABASE_NAME=storage/dev.sqlite3", "DATABASE_NAME=xlzxedu"
if ($content -match "(?m)^LEARNING_EVENT_QUARANTINE_KEY=\s*$") {
  $quarantineKey = & $Python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  $content = $content -replace "(?m)^LEARNING_EVENT_QUARANTINE_KEY=\s*$", "LEARNING_EVENT_QUARANTINE_KEY=$quarantineKey"
}
Set-Content -Encoding UTF8 $EnvPath $content

& $Python (Join-Path $Root "manage.py") migrate
& $Python (Join-Path $Root "manage.py") sync_learning_event_schemas
Write-Host "Switched to PostgreSQL settings and applied migrations."
