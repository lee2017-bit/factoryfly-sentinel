param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$InspectionId,

    [Parameter(Mandatory = $true)]
    [string]$BaselineId,

    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [Parameter(Mandatory = $true)]
    [string]$TelemetryPath,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ValidId {
    param(
        [string]$Value,
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Label is required."
    }

    if ($Value.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "$Label contains an invalid Windows filename character: $Value"
    }
}

Assert-ValidId -Value $InspectionId -Label "InspectionId"
Assert-ValidId -Value $BaselineId -Label "BaselineId"

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$VideoPath = [System.IO.Path]::GetFullPath($VideoPath)
$TelemetryPath = [System.IO.Path]::GetFullPath($TelemetryPath)

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project root not found: $ProjectRoot"
}

if (-not (Test-Path -LiteralPath $VideoPath -PathType Leaf)) {
    throw "Inspection video not found: $VideoPath"
}

if (-not (Test-Path -LiteralPath $TelemetryPath -PathType Leaf)) {
    throw "Inspection telemetry not found: $TelemetryPath"
}

$InspectionRoot = Join-Path $ProjectRoot $InspectionId
$VideoDir = Join-Path $InspectionRoot "video"
$TelemetryDir = Join-Path $InspectionRoot "telemetry"
$ManifestPath = Join-Path $InspectionRoot "input_manifest.json"
$ConfigPath = Join-Path $InspectionRoot "inspection_config.json"

@(
    $InspectionRoot,
    $VideoDir,
    $TelemetryDir,
    (Join-Path $InspectionRoot "frames"),
    (Join-Path $InspectionRoot "poses"),
    (Join-Path $InspectionRoot "localization"),
    (Join-Path $InspectionRoot "change_detection"),
    (Join-Path $InspectionRoot "reports"),
    (Join-Path $InspectionRoot "coverage"),
    (Join-Path $InspectionRoot "candidate_views"),
    (Join-Path $InspectionRoot "amd_rollouts")
) | ForEach-Object {
    New-Item -ItemType Directory -Force -Path $_ | Out-Null
}

if ((Test-Path -LiteralPath $ManifestPath) -and -not $Force) {
    throw @"
An inspection manifest already exists:
$ManifestPath

Use -Force to replace only the manifest and inspection_config.json.
Derived localization and analysis outputs are not deleted.
"@
}

$Video = Get-Item -LiteralPath $VideoPath
$Telemetry = Get-Item -LiteralPath $TelemetryPath

Write-Host "Calculating SHA256 hashes."
$VideoHash = (Get-FileHash -LiteralPath $Video.FullName -Algorithm SHA256).Hash
$TelemetryHash = (Get-FileHash -LiteralPath $Telemetry.FullName -Algorithm SHA256).Hash
$RegisteredAt = (Get-Date).ToString("o")

$Manifest = [ordered]@{
    inspection_id = $InspectionId
    baseline_id = $BaselineId
    status = "ready_for_processing"
    registered_at = $RegisteredAt

    video = [ordered]@{
        filename = $Video.Name
        full_path = $Video.FullName
        size_bytes = $Video.Length
        size_mb = [math]::Round($Video.Length / 1MB, 2)
        last_write_time = $Video.LastWriteTime.ToString("o")
        sha256 = $VideoHash
    }

    telemetry = [ordered]@{
        filename = $Telemetry.Name
        full_path = $Telemetry.FullName
        size_bytes = $Telemetry.Length
        size_mb = [math]::Round($Telemetry.Length / 1MB, 2)
        last_write_time = $Telemetry.LastWriteTime.ToString("o")
        sha256 = $TelemetryHash
    }
}

$Manifest |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path $ManifestPath -Encoding UTF8

$Config = [ordered]@{
    inspection_id = $InspectionId
    baseline_id = $BaselineId
    status = "ready_for_processing"
    video_file = $Video.FullName
    telemetry_file = $Telemetry.FullName
    registered_at = $RegisteredAt
}

$Config |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path $ConfigPath -Encoding UTF8

Write-Host ""
Write-Host "============================================================"
Write-Host "[PASS] Inspection inputs registered"
Write-Host "============================================================"
Write-Host "Inspection : $InspectionId"
Write-Host "Baseline   : $BaselineId"
Write-Host "Video      : $($Video.FullName)"
Write-Host "Video size : $([math]::Round($Video.Length / 1MB, 2)) MB"
Write-Host "Telemetry  : $($Telemetry.FullName)"
Write-Host "Manifest   : $ManifestPath"
Write-Host "Status     : ready_for_processing"
Write-Host "============================================================"
