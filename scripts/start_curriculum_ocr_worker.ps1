param(
  [ValidateSet("Auto", "Filesystem", "Redis")][string]$BrokerMode = "Auto",
  [ValidateRange(1, 8)][int]$CpuCount = 1,
  [switch]$ValidateOnly,
  [switch]$AllowUnboundedResources
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "curriculum_ocr_worker_common.ps1")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) {
  throw "Python environment not found: $Python"
}

if ($BrokerMode -eq "Auto") {
  Push-Location $Root
  try {
    $DetectedOutput = @(& $Python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); from django.conf import settings; url=settings.CELERY_BROKER_URL.lower(); print('Filesystem' if url.startswith('filesystem://') else 'Redis' if url.startswith(('redis://', 'rediss://')) else 'Unsupported')")
    if ($LASTEXITCODE -ne 0 -or $DetectedOutput.Count -eq 0) {
      throw "Could not detect the configured Celery broker mode."
    }
    $BrokerMode = [string]$DetectedOutput[-1]
    if ($BrokerMode -notin @("Filesystem", "Redis")) {
      throw "Unsupported Celery broker configured; expected filesystem:// or redis://."
    }
  }
  finally {
    Pop-Location
  }
}

$Layout = Get-CurriculumWorkerLayout -ProjectRoot $Root
Initialize-CurriculumWorkerDirectories -Layout $Layout
$ExistingMetadata = Get-CurriculumWorkerMetadata -Layout $Layout
$ExistingProcess = Get-VerifiedCurriculumWorkerProcess -Metadata $ExistingMetadata
if ($null -ne $ExistingProcess) {
  Write-Host "Curriculum OCR worker is already running (PID $($ExistingProcess.Id))."
  exit 0
}

if ($BrokerMode -eq "Filesystem") {
  & $Python -c "import pywintypes, win32file"
  if ($LASTEXITCODE -ne 0) {
    throw "The Windows filesystem broker requires pywin32. Run scripts\install_offline.ps1 first."
  }
  Set-CurriculumFilesystemEnvironment -Layout $Layout -Role "worker"
}

# Limit native numerical libraries before they are imported by OCR.
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

$env:CURRICULUM_EXPECTED_BROKER_MODE = $BrokerMode.ToLowerInvariant()
Push-Location $Root
try {
  & $Python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); from django.conf import settings; expected=os.environ['CURRICULUM_EXPECTED_BROKER_MODE']; url=settings.CELERY_BROKER_URL.lower(); assert settings.CELERY_TASK_ROUTES['curriculum_standards.process_version_pdf']['queue'] == 'curriculum_ocr'; assert (url.startswith('filesystem://') and settings.CELERY_RESULT_BACKEND == 'disabled://') if expected == 'filesystem' else url.startswith(('redis://', 'rediss://'))"
  if ($LASTEXITCODE -ne 0) {
    throw "Django/Celery curriculum queue configuration does not match -BrokerMode $BrokerMode."
  }
}
finally {
  Pop-Location
}

if ($ValidateOnly) {
  Write-Host "Curriculum OCR worker configuration is valid; no worker was started."
  Write-Host "Broker mode: $BrokerMode; queue: curriculum_ocr; concurrency: 1; prefetch: 1"
  exit 0
}

# A worker restart must also recover durable database jobs whose broker message
# was lost or deliberately parked during maintenance. Reusing the same task id
# makes duplicate delivery safe. Filesystem transport must publish with the
# producer-facing directory layout before switching back to the worker role.
if ($BrokerMode -eq "Filesystem") {
  Set-CurriculumFilesystemEnvironment -Layout $Layout -Role "producer"
}
Push-Location $Root
try {
  & $Python manage.py reconcile_curriculum_jobs --redispatch-stale-queued --queued-stale-seconds 300
  if ($LASTEXITCODE -ne 0) {
    throw "Queued curriculum-standard tasks could not be recovered."
  }
}
finally {
  Pop-Location
}
if ($BrokerMode -eq "Filesystem") {
  Set-CurriculumFilesystemEnvironment -Layout $Layout -Role "worker"
}

$NodeName = "curriculum-ocr@$env:COMPUTERNAME"
$Arguments = @(
  "-m", "celery",
  "-A", "config",
  "worker",
  "--pool=solo",
  "--queues=curriculum_ocr",
  "--concurrency=1",
  "--prefetch-multiplier=1",
  "--hostname=$NodeName",
  "--loglevel=INFO",
  "--logfile=$($Layout.WorkerLog)",
  "--without-gossip",
  "--without-mingle"
)

$Worker = Start-Process `
  -FilePath $Python `
  -ArgumentList $Arguments `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $Layout.StdoutLog `
  -RedirectStandardError $Layout.StderrLog `
  -PassThru

$PriorityApplied = $true
try {
  $Worker.PriorityClass = "BelowNormal"
}
catch {
  $PriorityApplied = $false
  Write-Warning "Could not set BelowNormal priority: $($_.Exception.Message)"
}

$AffinityApplied = $true
try {
  $AvailableCpuCount = [Environment]::ProcessorCount
  $EffectiveCpuCount = [Math]::Min($CpuCount, [Math]::Min($AvailableCpuCount, 63))
  [UInt64]$AffinityMask = 0
  for ($Index = 0; $Index -lt $EffectiveCpuCount; $Index++) {
    $AffinityMask = $AffinityMask -bor ([UInt64]1 -shl $Index)
  }
  # Process.ProcessorAffinity expects a signed pointer-sized value.  An
  # explicit Int64 constructor works on 64-bit Windows; a direct UInt64 cast
  # is rejected by Windows PowerShell 5.1 even when the mask is small.
  $Worker.ProcessorAffinity = [IntPtr]::new([Int64]$AffinityMask)
}
catch {
  $AffinityApplied = $false
  Write-Warning "Could not set CPU affinity: $($_.Exception.Message)"
}

if ((!$PriorityApplied -or !$AffinityApplied) -and !$AllowUnboundedResources) {
  Stop-Process -Id $Worker.Id -Force -ErrorAction SilentlyContinue
  throw "The worker was stopped because its Windows priority/CPU limits could not be applied. Fix the service account permissions, or use -AllowUnboundedResources only under separate OS-level limits."
}

Start-Sleep -Seconds 2
$Worker.Refresh()
if ($Worker.HasExited) {
  $Tail = ""
  if (Test-Path -LiteralPath $Layout.StderrLog -PathType Leaf) {
    $Tail = (Get-Content -LiteralPath $Layout.StderrLog -Tail 20) -join [Environment]::NewLine
  }
  throw "Curriculum OCR worker exited during startup.`n$Tail"
}

[PSCustomObject]@{
  pid = $Worker.Id
  node_name = $NodeName
  broker_mode = $BrokerMode
  queue = "curriculum_ocr"
  concurrency = 1
  prefetch = 1
  cpu_count = $EffectiveCpuCount
  priority_applied = $PriorityApplied
  affinity_applied = $AffinityApplied
  started_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $Layout.MetadataPath -Encoding UTF8

Write-Host "Curriculum OCR worker started."
Write-Host "PID: $($Worker.Id); queue: curriculum_ocr; concurrency: 1; prefetch: 1"
if ($PriorityApplied -and $AffinityApplied) {
  Write-Host "Priority: BelowNormal; CPU affinity: first $EffectiveCpuCount logical processor(s)"
}
else {
  Write-Warning "One or more Windows resource limits could not be applied; review the warnings above before processing documents."
}
Write-Host "Log: $($Layout.WorkerLog)"
