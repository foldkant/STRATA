param([int]$Port = 0)

$ErrorActionPreference = "Stop"
Write-Warning "Waitress/WGSI does not support classroom WebSocket. Starting the ASGI service instead."
& (Join-Path $PSScriptRoot "run_asgi.ps1") -Port $Port
