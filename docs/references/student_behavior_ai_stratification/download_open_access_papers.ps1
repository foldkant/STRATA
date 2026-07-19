param(
    [int]$RequestDelayMs = 150,
    [int]$QueryFromId = 1
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$manifestPath = Join-Path $root "papers_manifest.csv"
$papersPath = Join-Path $root "papers"
$reportPath = Join-Path $root "oa_download_report.csv"

New-Item -ItemType Directory -Force -Path $papersPath | Out-Null
$resolvedPapersPath = (Resolve-Path -LiteralPath $papersPath).Path
if (-not $resolvedPapersPath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The papers directory is outside the reference folder."
}

$report = foreach ($item in (Import-Csv -LiteralPath $manifestPath)) {
    $status = "metadata_only"
    $oaStatus = "unknown"
    $pdfUrl = ""
    $note = ""
    $fileName = "{0}_{1}.pdf" -f $item.id, $item.citekey
    $targetPath = Join-Path $resolvedPapersPath $fileName
    $tempPath = "$targetPath.part"
    $queriedOpenAlex = $false

    try {
        if (Test-Path -LiteralPath $targetPath) {
            $stream = [System.IO.File]::OpenRead($targetPath)
            try {
                $header = New-Object byte[] 4
                [void]$stream.Read($header, 0, 4)
                if ([System.Text.Encoding]::ASCII.GetString($header) -ne "%PDF") {
                    throw "Existing file failed PDF signature validation."
                }
            } finally {
                $stream.Dispose()
            }
            $status = "downloaded"
            $oaStatus = "previously_verified"
            $note = "Existing verified file retained."
        } elseif ([int]$item.id -lt $QueryFromId) {
            $note = "Metadata-only record not rechecked in this run."
        } else {
            $queriedOpenAlex = $true
            $filter = "doi:$($item.doi)"
            $select = "id,doi,title,publication_year,open_access,best_oa_location,content_urls,locations"
            $uri = "https://api.openalex.org/works?filter=$([uri]::EscapeDataString($filter))&select=$([uri]::EscapeDataString($select))&per-page=1"
            $response = Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{ "User-Agent" = "STRATA-research/1.0" } -TimeoutSec 30
            $payload = $response.Content | ConvertFrom-Json
            if ([int]$payload.meta.count -lt 1) {
                throw "OpenAlex metadata not found."
            }

            $work = $payload.results[0]
            $oaStatus = [string]$work.open_access.oa_status
            $pdfUrl = [string]$work.best_oa_location.pdf_url
            if (-not $pdfUrl) {
                $location = $work.locations | Where-Object { $_.is_oa -and $_.pdf_url } | Select-Object -First 1
                if ($location) {
                    $pdfUrl = [string]$location.pdf_url
                }
            }
            if (-not $pdfUrl -and $work.open_access.is_oa -and $work.content_urls.pdf) {
                $pdfUrl = [string]$work.content_urls.pdf
            }

            if (-not $work.open_access.is_oa) {
                $note = "No legal open-access full text reported by OpenAlex."
            } elseif (-not $pdfUrl) {
                $note = "Open access reported, but no direct PDF URL was available."
            } else {
                Invoke-WebRequest -UseBasicParsing -Uri $pdfUrl -OutFile $tempPath -Headers @{ "User-Agent" = "Mozilla/5.0 STRATA-research/1.0" } -TimeoutSec 90
                $bytes = [System.IO.File]::ReadAllBytes($tempPath)
                $signature = if ($bytes.Length -ge 4) { [System.Text.Encoding]::ASCII.GetString($bytes, 0, 4) } else { "" }
                if ($signature -ne "%PDF") {
                    Remove-Item -LiteralPath $tempPath -Force
                    throw "Downloaded response was not a PDF."
                }
                Move-Item -LiteralPath $tempPath -Destination $targetPath
                $status = "downloaded"
                $note = "Validated by PDF file signature."
            }
        }
    } catch {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force
        }
        $note = $_.Exception.Message
    }

    Write-Host "[$($item.id)] $($item.citekey): $status ($oaStatus)"
    [pscustomobject]@{
        id = $item.id
        citekey = $item.citekey
        doi = $item.doi
        topic = $item.topic
        oa_status = $oaStatus
        full_text_status = $status
        pdf_file = if ($status -eq "downloaded") { $fileName } else { "" }
        source_url = $pdfUrl
        note = $note
    }
    if ($queriedOpenAlex) {
        Start-Sleep -Milliseconds $RequestDelayMs
    }
}

$report | Export-Csv -LiteralPath $reportPath -NoTypeInformation -Encoding UTF8
$report | Group-Object full_text_status | Select-Object Name, Count | Format-Table
