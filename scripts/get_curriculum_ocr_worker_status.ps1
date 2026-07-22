$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "curriculum_ocr_worker_common.ps1")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Layout = Get-CurriculumWorkerLayout -ProjectRoot $Root
$Metadata = Get-CurriculumWorkerMetadata -Layout $Layout
$Worker = Get-VerifiedCurriculumWorkerProcess -Metadata $Metadata
$OverallExitCode = 0

if ($null -eq $Worker) {
  Write-Host "Worker process: stopped or metadata is stale"
  $OverallExitCode = 1
}
else {
  $Worker.Refresh()
  $PriorityApplied = "unknown"
  $AffinityApplied = "unknown"
  $RequestedCpuCount = "unknown"
  if ($Metadata.PSObject.Properties.Name -contains "priority_applied") {
    $PriorityApplied = $Metadata.priority_applied
  }
  if ($Metadata.PSObject.Properties.Name -contains "affinity_applied") {
    $AffinityApplied = $Metadata.affinity_applied
  }
  if ($Metadata.PSObject.Properties.Name -contains "cpu_count") {
    $RequestedCpuCount = $Metadata.cpu_count
  }
  Write-Host "Worker process: running"
  Write-Host "PID: $($Worker.Id); priority: $($Worker.PriorityClass); working set MB: $([Math]::Round($Worker.WorkingSet64 / 1MB, 1))"
  Write-Host "Broker mode: $($Metadata.broker_mode); queue: $($Metadata.queue); concurrency: $($Metadata.concurrency); prefetch: $($Metadata.prefetch)"
  Write-Host "Resource limits applied: priority=$PriorityApplied; affinity=$AffinityApplied; requested CPU count=$RequestedCpuCount"
  Write-Host "Started: $($Metadata.started_at)"
}

if (Test-Path -LiteralPath $Layout.ProducerOut -PathType Container) {
  $PendingFiles = @(Get-ChildItem -LiteralPath $Layout.ProducerOut -File -Filter "*.curriculum_ocr.msg" -ErrorAction SilentlyContinue).Count
  Write-Host "Filesystem broker pending message files: $PendingFiles"
}

if (Test-Path -LiteralPath $Python -PathType Leaf) {
  $DatabaseStatus = Invoke-CurriculumQueueDatabaseStatus -Python $Python -ProjectRoot $Root
  if ($DatabaseStatus -ne 0) {
    Write-Warning "The database status command returned exit code $DatabaseStatus."
    $OverallExitCode = 1
  }
}
else {
  Write-Warning "Python environment not found; database job status was not checked."
}

Write-Host "Worker log: $($Layout.WorkerLog)"
exit $OverallExitCode
