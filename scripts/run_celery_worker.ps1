$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Celery = Join-Path $Root ".venv\Scripts\celery.exe"
Set-Location $Root
# The general worker must not consume CPU-heavy curriculum OCR jobs. Those are
# handled by start_curriculum_ocr_worker.ps1 with concurrency/prefetch fixed at 1.
# The role variable is ignored by Redis and makes this worker a consumer when a
# developer has explicitly selected the single-host filesystem fallback.
$env:CURRICULUM_CELERY_FILESYSTEM_ROLE = "worker"
& $Celery -A config worker -l info --pool=solo --queues=celery
