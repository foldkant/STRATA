param([int]$Port = 0)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "run_asgi.ps1") -Port $Port
