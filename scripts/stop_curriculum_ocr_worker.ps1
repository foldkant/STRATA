param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "curriculum_ocr_worker_common.ps1")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Layout = Get-CurriculumWorkerLayout -ProjectRoot $Root
$Metadata = Get-CurriculumWorkerMetadata -Layout $Layout
$Worker = Get-VerifiedCurriculumWorkerProcess -Metadata $Metadata

if ($null -eq $Worker) {
  Write-Host "Curriculum OCR worker is not running."
  exit 0
}

$StatusExitCode = Invoke-CurriculumQueueDatabaseStatus `
  -Python $Python `
  -ProjectRoot $Root `
  -ExitNonzeroIfActive

if ($StatusExitCode -ne 0 -and !$Force) {
  Write-Error "A curriculum document is running/cancelling, or its database state could not be verified. Cancel it in the administrator task center and wait for a final state before stopping the worker. Use -Force only for an unrecoverable worker; stale-job reconciliation will then mark the interrupted job failed." -ErrorAction Continue
  exit 2
}

if ($StatusExitCode -ne 0 -and $Force) {
  Write-Warning "Forcing an active worker to stop. Published/formal page data stays unchanged, but the interrupted job will require stale-job reconciliation and a manual retry."
}

# The Kombu filesystem transport does not support Celery remote control.
# After the database confirms no active job, terminating this dedicated process
# cannot interrupt unrelated queues. Queued message files remain on disk.
Stop-Process -Id $Worker.Id -Force
$Worker.WaitForExit(10000) | Out-Null
if (!$Worker.HasExited) {
  throw "Worker PID $($Worker.Id) did not exit."
}

if (Test-Path -LiteralPath $Layout.MetadataPath -PathType Leaf) {
  Remove-Item -LiteralPath $Layout.MetadataPath -Force
}
Write-Host "Curriculum OCR worker stopped. Queued jobs remain queued."
