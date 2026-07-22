Set-StrictMode -Version Latest

function Get-CurriculumWorkerLayout {
  param([Parameter(Mandatory = $true)][string]$ProjectRoot)

  $QueueRoot = Join-Path $ProjectRoot "storage\celery\curriculum_ocr"
  $RuntimeRoot = Join-Path $ProjectRoot "tmp\curriculum_ocr_worker"
  $LogRoot = Join-Path $ProjectRoot "logs\curriculum_ocr_worker"
  [PSCustomObject]@{
    ProjectRoot = $ProjectRoot
    QueueRoot = $QueueRoot
    ProducerOut = Join-Path $QueueRoot "producer-out"
    WorkerOut = Join-Path $QueueRoot "worker-out"
    Processed = Join-Path $QueueRoot "processed"
    Control = Join-Path $QueueRoot "control"
    RuntimeRoot = $RuntimeRoot
    MetadataPath = Join-Path $RuntimeRoot "worker.json"
    LogRoot = $LogRoot
    WorkerLog = Join-Path $LogRoot "worker.log"
    StdoutLog = Join-Path $LogRoot "stdout.log"
    StderrLog = Join-Path $LogRoot "stderr.log"
  }
}

function Initialize-CurriculumWorkerDirectories {
  param([Parameter(Mandatory = $true)]$Layout)

  @(
    $Layout.ProducerOut,
    $Layout.WorkerOut,
    $Layout.Processed,
    $Layout.Control,
    $Layout.RuntimeRoot,
    $Layout.LogRoot
  ) | ForEach-Object {
    New-Item -ItemType Directory -Path $_ -Force | Out-Null
  }
}

function Get-CurriculumWorkerMetadata {
  param([Parameter(Mandatory = $true)]$Layout)

  if (!(Test-Path -LiteralPath $Layout.MetadataPath -PathType Leaf)) {
    return $null
  }
  try {
    return Get-Content -LiteralPath $Layout.MetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
  }
  catch {
    return $null
  }
}

function Get-VerifiedCurriculumWorkerProcess {
  param([AllowNull()]$Metadata)

  if ($null -eq $Metadata -or $null -eq $Metadata.pid) {
    return $null
  }
  $ProcessId = 0
  if (![int]::TryParse([string]$Metadata.pid, [ref]$ProcessId)) {
    return $null
  }
  $Win32Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if ($null -eq $Win32Process) {
    return $null
  }
  $CommandLine = [string]$Win32Process.CommandLine
  if (
    $CommandLine -notmatch "(?i)(python|celery)" -or
    $CommandLine -notmatch "(?i)curriculum_ocr" -or
    $CommandLine -notmatch "(?i)(-A\s+config|--app(=|\s+)config)"
  ) {
    return $null
  }
  return Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Set-CurriculumFilesystemEnvironment {
  param(
    [Parameter(Mandatory = $true)]$Layout,
    [ValidateSet("producer", "worker")][string]$Role
  )

  $env:CELERY_BROKER_URL = "filesystem://"
  $env:CELERY_RESULT_BACKEND = "disabled://"
  $env:CURRICULUM_CELERY_FILESYSTEM_ROOT = $Layout.QueueRoot
  $env:CURRICULUM_CELERY_FILESYSTEM_ROLE = $Role
}

function Invoke-CurriculumQueueDatabaseStatus {
  param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [switch]$ExitNonzeroIfActive
  )

  $Arguments = @("manage.py", "curriculum_queue_status")
  if ($ExitNonzeroIfActive) {
    $Arguments += "--exit-nonzero-if-active"
  }
  Push-Location $ProjectRoot
  try {
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
      $CommandOutput = @(& $Python @Arguments 2>&1)
    }
    finally {
      $ErrorActionPreference = $PreviousErrorActionPreference
    }
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -in @(0, 2)) {
      $CommandOutput | ForEach-Object { Write-Host ([string]$_) }
    }
    elseif ($CommandOutput.Count -gt 0) {
      Write-Warning "Could not read curriculum queue database status: $([string]$CommandOutput[-1])"
    }
    return $ExitCode
  }
  finally {
    Pop-Location
  }
}
