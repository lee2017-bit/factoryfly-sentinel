param(
    [Parameter(Mandatory = $true)]
    [string]$BaselineRoot,

    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [double]$Fps = 4.0,

    [string]$ColmapBat = "C:\Tools\COLMAP\COLMAP.bat",

    [string]$FfmpegExe = "ffmpeg",

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

function Write-Stage {
    param(
        [string]$Message
    )

    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Message
    Write-Host "============================================================"
}


function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StageName,

        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    Write-Stage $StageName

    Write-Host "Executable:"
    Write-Host $Executable

    Write-Host ""
    Write-Host "Arguments:"
    Write-Host ($Arguments -join " ")

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    try {
        & $Executable @Arguments 2>&1 |
            Tee-Object -FilePath $LogPath

        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    if ($ExitCode -ne 0) {
        throw "$StageName failed with exit code $ExitCode. Log: $LogPath"
    }

    Write-Host "[PASS] $StageName"
}


# ------------------------------------------------------------
# Resolve and validate inputs
# ------------------------------------------------------------

$BaselineRoot = [System.IO.Path]::GetFullPath($BaselineRoot)
$VideoPath = [System.IO.Path]::GetFullPath($VideoPath)

if (-not (Test-Path $VideoPath -PathType Leaf)) {
    throw "Baseline video not found: $VideoPath"
}

if (-not (Test-Path $ColmapBat -PathType Leaf)) {
    throw "COLMAP.bat not found: $ColmapBat"
}

if ($FfmpegExe -eq "ffmpeg") {
    $FfmpegCommand = Get-Command `
        ffmpeg `
        -ErrorAction SilentlyContinue

    if ($null -eq $FfmpegCommand) {
        throw @"
FFmpeg was not found in PATH.

Check with:
    Get-Command ffmpeg

Install or provide its full path using:
    -FfmpegExe "C:\path\to\ffmpeg.exe"
"@
    }

    $FfmpegExe = $FfmpegCommand.Source
}
elseif (-not (Test-Path $FfmpegExe -PathType Leaf)) {
    throw "FFmpeg executable not found: $FfmpegExe"
}


# ------------------------------------------------------------
# Directory layout
# ------------------------------------------------------------

$FramesDir = Join-Path $BaselineRoot "frames\raw"
$ReconstructionDir = Join-Path $BaselineRoot "reconstruction"

$DatabasePath = Join-Path `
    $ReconstructionDir `
    "database.db"

$SparseDir = Join-Path `
    $ReconstructionDir `
    "sparse"

$BestModelDir = Join-Path `
    $ReconstructionDir `
    "sparse_best"

$ModelScanDir = Join-Path `
    $ReconstructionDir `
    "model_scan"

$PosesDir = Join-Path $BaselineRoot "poses"
$ReportsDir = Join-Path $BaselineRoot "reports"
$LogsDir = Join-Path $BaselineRoot "logs"

$ManifestPath = Join-Path `
    $BaselineRoot `
    "baseline_manifest.json"

$SummaryPath = Join-Path `
    $ReportsDir `
    "baseline_summary.json"


# ------------------------------------------------------------
# Clean or protect previous outputs
# ------------------------------------------------------------

if ($Force) {
    Write-Stage "Cleaning previous derived outputs"

    @(
        $FramesDir,
        $ReconstructionDir,
        $PosesDir,
        $ReportsDir,
        $LogsDir
    ) |
    ForEach-Object {
        if (Test-Path $_) {
            Remove-Item `
                $_ `
                -Recurse `
                -Force
        }
    }
}
else {
    if (
        (Test-Path $DatabasePath) -or
        (Test-Path $SparseDir)
    ) {
        throw @"
Baseline output already exists.

Use a new BaselineRoot or rerun with:
    -Force
"@
    }
}


# ------------------------------------------------------------
# Create folders
# ------------------------------------------------------------

@(
    $BaselineRoot,
    $FramesDir,
    $ReconstructionDir,
    $SparseDir,
    $ModelScanDir,
    $PosesDir,
    $ReportsDir,
    $LogsDir
) |
ForEach-Object {
    New-Item `
        -ItemType Directory `
        -Force `
        -Path $_ |
    Out-Null
}


# ------------------------------------------------------------
# Register baseline input
# ------------------------------------------------------------

Write-Stage "Registering baseline video"

$Video = Get-Item $VideoPath

$VideoHash = (
    Get-FileHash `
        $VideoPath `
        -Algorithm SHA256
).Hash

$Manifest = [ordered]@{
    baseline_id = Split-Path $BaselineRoot -Leaf

    registered_at = (
        Get-Date
    ).ToString("o")

    status = "processing"

    video = [ordered]@{
        filename = $Video.Name
        full_path = $Video.FullName
        size_bytes = $Video.Length

        size_mb = [math]::Round(
            $Video.Length / 1MB,
            2
        )

        sha256 = $VideoHash
    }

    processing = [ordered]@{
        fps = $Fps
        camera_model = "SIMPLE_RADIAL"
        single_camera = $true
        matcher = "exhaustive"
    }
}

$Manifest |
    ConvertTo-Json -Depth 10 |
    Set-Content `
        -Path $ManifestPath `
        -Encoding UTF8


# ------------------------------------------------------------
# Extract frames
# ------------------------------------------------------------

$FramePattern = Join-Path `
    $FramesDir `
    "frame_%06d.jpg"

Invoke-ExternalCommand `
    -StageName "1 / 5 - Extract baseline frames" `
    -Executable $FfmpegExe `
    -Arguments @(
        "-hide_banner",
        "-loglevel", "warning",
        "-y",
        "-i", $VideoPath,
        "-vf", "fps=$Fps",
        "-q:v", "2",
        $FramePattern
    ) `
    -LogPath (
        Join-Path $LogsDir "01_frame_extraction.log"
    )

$FrameFiles = @(
    Get-ChildItem `
        $FramesDir `
        -Filter "*.jpg" `
        -File
)

if ($FrameFiles.Count -lt 20) {
    throw "Too few frames were extracted: $($FrameFiles.Count)"
}

Write-Host "Extracted frames: $($FrameFiles.Count)"


# ------------------------------------------------------------
# COLMAP feature extraction
# ------------------------------------------------------------

Invoke-ExternalCommand `
    -StageName "2 / 5 - COLMAP feature extraction" `
    -Executable $ColmapBat `
    -Arguments @(
        "feature_extractor",
        "--database_path", $DatabasePath,
        "--image_path", $FramesDir,
        "--ImageReader.camera_model", "SIMPLE_RADIAL",
        "--ImageReader.single_camera", "1",
        "--FeatureExtraction.use_gpu", "1"
    ) `
    -LogPath (
        Join-Path $LogsDir "02_feature_extraction.log"
    )


# ------------------------------------------------------------
# COLMAP matching
# ------------------------------------------------------------

Invoke-ExternalCommand `
    -StageName "3 / 5 - COLMAP exhaustive matching" `
    -Executable $ColmapBat `
    -Arguments @(
        "exhaustive_matcher",
        "--database_path", $DatabasePath,
        "--FeatureMatching.use_gpu", "1"
    ) `
    -LogPath (
        Join-Path $LogsDir "03_exhaustive_matching.log"
    )


# ------------------------------------------------------------
# COLMAP sparse reconstruction
# ------------------------------------------------------------

Invoke-ExternalCommand `
    -StageName "4 / 5 - COLMAP sparse reconstruction" `
    -Executable $ColmapBat `
    -Arguments @(
        "mapper",
        "--database_path", $DatabasePath,
        "--image_path", $FramesDir,
        "--output_path", $SparseDir
    ) `
    -LogPath (
        Join-Path $LogsDir "04_mapper.log"
    )


# ------------------------------------------------------------
# Find generated sparse models
# ------------------------------------------------------------

$SparseModels = @(
    Get-ChildItem `
        $SparseDir `
        -Directory
)

if ($SparseModels.Count -eq 0) {
    throw "COLMAP mapper created no sparse models."
}

$ModelResults = @()

foreach ($Model in $SparseModels) {
    $TextOutput = Join-Path `
        $ModelScanDir `
        $Model.Name

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $TextOutput |
    Out-Null

    Invoke-ExternalCommand `
        -StageName "Analyze sparse model $($Model.Name)" `
        -Executable $ColmapBat `
        -Arguments @(
            "model_converter",
            "--input_path", $Model.FullName,
            "--output_path", $TextOutput,
            "--output_type", "TXT"
        ) `
        -LogPath (
            Join-Path `
                $LogsDir `
                "05_model_converter_$($Model.Name).log"
        )

    $ImagesText = Join-Path `
        $TextOutput `
        "images.txt"

    $PointsText = Join-Path `
        $TextOutput `
        "points3D.txt"

    $ImageDataLines = @(
        Get-Content $ImagesText |
        Where-Object {
            -not $_.StartsWith("#")
        }
    )

    $RegisteredImages = [int][math]::Floor(
        $ImageDataLines.Count / 2
    )

    $PointLines = @(
        Get-Content $PointsText |
        Where-Object {
            $_ -and
            -not $_.StartsWith("#")
        }
    )

    $ModelResults += [pscustomobject]@{
        ModelPath = $Model.FullName
        ModelName = $Model.Name
        RegisteredImages = $RegisteredImages
        SparsePoints = $PointLines.Count
        TextOutput = $TextOutput
    }
}


# ------------------------------------------------------------
# Select best model
# ------------------------------------------------------------

$BestModel = $ModelResults |
    Sort-Object `
        RegisteredImages,
        SparsePoints `
        -Descending |
    Select-Object -First 1

Write-Stage "Selected best sparse model"

$ModelResults |
    Sort-Object RegisteredImages -Descending |
    Format-Table `
        ModelName,
        RegisteredImages,
        SparsePoints

Write-Host "Best model:"
Write-Host $BestModel.ModelPath

New-Item `
    -ItemType Directory `
    -Force `
    -Path $BestModelDir |
Out-Null

Copy-Item `
    -Path (
        Join-Path $BestModel.ModelPath "*"
    ) `
    -Destination $BestModelDir `
    -Recurse `
    -Force


# ------------------------------------------------------------
# Export best model to TXT
# ------------------------------------------------------------

Invoke-ExternalCommand `
    -StageName "5 / 5 - Export best model poses" `
    -Executable $ColmapBat `
    -Arguments @(
        "model_converter",
        "--input_path", $BestModelDir,
        "--output_path", $PosesDir,
        "--output_type", "TXT"
    ) `
    -LogPath (
        Join-Path $LogsDir "06_export_best_model.log"
    )


# ------------------------------------------------------------
# Write summary
# ------------------------------------------------------------

$RegistrationRate = [math]::Round(
    100.0 *
    $BestModel.RegisteredImages /
    $FrameFiles.Count,
    2
)

$Summary = [ordered]@{
    baseline_id = Split-Path $BaselineRoot -Leaf
    status = "ready"
    completed_at = (Get-Date).ToString("o")

    source_video = $VideoPath
    video_sha256 = $VideoHash

    fps = $Fps
    extracted_frames = $FrameFiles.Count

    registered_frames = $BestModel.RegisteredImages
    registration_rate_percent = $RegistrationRate

    sparse_points = $BestModel.SparsePoints
    sparse_model_count = $SparseModels.Count

    best_model_source = $BestModel.ModelPath
    best_model_path = $BestModelDir

    database_path = $DatabasePath
    frame_path = $FramesDir
    pose_export_path = $PosesDir

    camera_model = "SIMPLE_RADIAL"
    matching_method = "exhaustive"
}

$Summary |
    ConvertTo-Json -Depth 10 |
    Set-Content `
        -Path $SummaryPath `
        -Encoding UTF8

$Manifest.status = "ready"
$Manifest.summary_file = $SummaryPath
$Manifest.best_model_path = $BestModelDir

$Manifest |
    ConvertTo-Json -Depth 10 |
    Set-Content `
        -Path $ManifestPath `
        -Encoding UTF8


# ------------------------------------------------------------
# Final output
# ------------------------------------------------------------

Write-Stage "[PASS] BASELINE PIPELINE COMPLETED"

Write-Host "Baseline root       : $BaselineRoot"
Write-Host "Extracted frames    : $($FrameFiles.Count)"
Write-Host "Registered frames   : $($BestModel.RegisteredImages)"
Write-Host "Registration rate   : $RegistrationRate %"
Write-Host "Sparse points       : $($BestModel.SparsePoints)"
Write-Host "Best model          : $BestModelDir"
Write-Host "Pose export         : $PosesDir"
Write-Host "Summary             : $SummaryPath"
