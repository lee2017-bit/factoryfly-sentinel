param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$InspectionId,

    [Parameter(Mandatory = $true)]
    [string]$BaselineId,

    [double]$Fps = 4.0,

    [string]$ColmapBat = "C:\Tools\COLMAP\COLMAP.bat",

    [string]$FfmpegExe = "ffmpeg",

    [string]$PythonExe = "python",

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


function Write-Stage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Message
    Write-Host "============================================================"
}


function Invoke-NativeCommand {
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

    try {
        # Windows PowerShell 5.1 converts native stderr output into
        # NativeCommandError records. FFmpeg and COLMAP routinely write
        # progress and warnings to stderr even when they succeed.
        $ErrorActionPreference = "Continue"

        & $Executable @Arguments 2>&1 |
            ForEach-Object {
                $_.ToString()
            } |
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


function Resolve-Executable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [string]$DisplayName
    )

    if (Test-Path -LiteralPath $Value -PathType Leaf) {
        return (
            Get-Item -LiteralPath $Value
        ).FullName
    }

    $Command = Get-Command $Value -ErrorAction SilentlyContinue

    if ($null -eq $Command) {
        throw "$DisplayName was not found: $Value"
    }

    return $Command.Source
}


function New-LinkedFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,

        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $Parent = Split-Path $Destination -Parent

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $Parent |
    Out-Null

    if (Test-Path -LiteralPath $Destination) {
        Remove-Item `
            -LiteralPath $Destination `
            -Force
    }

    try {
        New-Item `
            -ItemType HardLink `
            -Path $Destination `
            -Target $Source |
        Out-Null
    }
    catch {
        Copy-Item `
            -LiteralPath $Source `
            -Destination $Destination `
            -Force
    }
}


$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$InspectionRoot = Join-Path $ProjectRoot $InspectionId
$BaselineRoot = Join-Path (
    Join-Path $ProjectRoot "baseline"
) $BaselineId

$ManifestPath = Join-Path $InspectionRoot "input_manifest.json"
$BaselineSummaryPath = Join-Path (
    Join-Path $BaselineRoot "reports"
) "baseline_summary.json"

$AnalyzerScript = Join-Path (
    Join-Path $ProjectRoot "shared\scripts"
) "analyze_colmap_registration.py"

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Inspection manifest not found: $ManifestPath"
}

if (-not (Test-Path -LiteralPath $BaselineSummaryPath -PathType Leaf)) {
    throw "Baseline summary not found: $BaselineSummaryPath"
}

if (-not (Test-Path -LiteralPath $AnalyzerScript -PathType Leaf)) {
    throw "Registration analyzer not found: $AnalyzerScript"
}

if (-not (Test-Path -LiteralPath $ColmapBat -PathType Leaf)) {
    throw "COLMAP.bat not found: $ColmapBat"
}

$FfmpegExe = Resolve-Executable `
    -Value $FfmpegExe `
    -DisplayName "FFmpeg"

$PythonExe = Resolve-Executable `
    -Value $PythonExe `
    -DisplayName "Python"

$Manifest = Get-Content `
    -LiteralPath $ManifestPath `
    -Raw |
ConvertFrom-Json

$BaselineSummary = Get-Content `
    -LiteralPath $BaselineSummaryPath `
    -Raw |
ConvertFrom-Json

if ($Manifest.status -ne "ready_for_processing") {
    throw "Inspection manifest status is not ready_for_processing."
}

if ($Manifest.baseline_id -ne $BaselineId) {
    throw "Inspection baseline mismatch. Manifest=$($Manifest.baseline_id), requested=$BaselineId"
}

if ($BaselineSummary.status -ne "ready") {
    throw "Baseline summary status is not ready."
}

$VideoPath = [string]$Manifest.video.full_path
$VideoHash = [string]$Manifest.video.sha256
$BaselineDatabase = [string]$BaselineSummary.database_path
$BaselineModel = [string]$BaselineSummary.best_model_path
$BaselinePoseText = Join-Path (
    Join-Path $BaselineRoot "poses"
) "cameras.txt"

foreach ($RequiredPath in @(
    $VideoPath,
    $BaselineDatabase,
    $BaselineModel,
    $BaselinePoseText
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required input not found: $RequiredPath"
    }
}

$FramesRoot = Join-Path $InspectionRoot "frames"
$FramesDir = Join-Path $FramesRoot "raw"
$FrameMetadataPath = Join-Path $FramesRoot "frame_extraction.json"

$LocalizationParent = Join-Path $InspectionRoot "localization"
$OutputRoot = Join-Path $LocalizationParent $BaselineId
$ReportsDir = Join-Path $OutputRoot "reports"
$LogsDir = Join-Path $OutputRoot "logs"
$WorkDir = Join-Path $OutputRoot "work"
$WorkDatabase = Join-Path $WorkDir "database.db"
$WorkImages = Join-Path $WorkDir "images"
$WorkInspectionImages = Join-Path $WorkImages "inspection"
$ImageListPath = Join-Path $WorkDir "inspection_image_list.txt"
$InputModel = Join-Path $WorkDir "input_model"
$RegisteredModel = Join-Path $OutputRoot "registered_model"
$ModelTextDir = Join-Path $OutputRoot "model_txt"
$SummaryPath = Join-Path $ReportsDir "localization_summary.json"

if (
    (Test-Path -LiteralPath $SummaryPath -PathType Leaf) -and
    (-not $Force)
) {
    throw "A completed localization already exists. Use -Force to overwrite: $SummaryPath"
}

if ($Force -and (Test-Path -LiteralPath $OutputRoot)) {
    Write-Stage "Cleaning previous localization output"
    Remove-Item `
        -LiteralPath $OutputRoot `
        -Recurse `
        -Force
}

if (Test-Path -LiteralPath $WorkDir) {
    Remove-Item `
        -LiteralPath $WorkDir `
        -Recurse `
        -Force
}

foreach ($Directory in @(
    $FramesRoot,
    $LocalizationParent,
    $OutputRoot,
    $ReportsDir,
    $LogsDir,
    $WorkDir,
    $WorkImages,
    $WorkInspectionImages,
    $InputModel,
    $RegisteredModel,
    $ModelTextDir
)) {
    New-Item `
        -ItemType Directory `
        -Force `
        -Path $Directory |
    Out-Null
}

$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()


# ------------------------------------------------------------
# 1. Extract or validate inspection frames
# ------------------------------------------------------------

$NeedFrameExtraction = $true

if (
    (Test-Path -LiteralPath $FrameMetadataPath -PathType Leaf) -and
    (Test-Path -LiteralPath $FramesDir -PathType Container)
) {
    try {
        $FrameMetadata = Get-Content `
            -LiteralPath $FrameMetadataPath `
            -Raw |
        ConvertFrom-Json

        $ExistingFrames = @(
            Get-ChildItem `
                -LiteralPath $FramesDir `
                -File |
            Where-Object {
                $_.Extension.ToLower() -in @(
                    ".jpg",
                    ".jpeg",
                    ".png"
                )
            }
        )

        $NeedFrameExtraction = -not (
            ([string]$FrameMetadata.video_sha256 -eq $VideoHash) -and
            ([double]$FrameMetadata.fps -eq $Fps) -and
            ($ExistingFrames.Count -gt 0)
        )
    }
    catch {
        $NeedFrameExtraction = $true
    }
}

if ($NeedFrameExtraction) {
    Write-Stage "1 / 6 - Extract inspection frames"

    if (Test-Path -LiteralPath $FramesDir) {
        Remove-Item `
            -LiteralPath $FramesDir `
            -Recurse `
            -Force
    }

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $FramesDir |
    Out-Null

    $FramePattern = Join-Path $FramesDir "frame_%06d.jpg"

    Invoke-NativeCommand `
        -StageName "Inspection frame extraction" `
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

    $ExtractedFrames = @(
        Get-ChildItem `
            -LiteralPath $FramesDir `
            -File |
        Where-Object {
            $_.Extension.ToLower() -in @(
                ".jpg",
                ".jpeg",
                ".png"
            )
        } |
        Sort-Object Name
    )

    if ($ExtractedFrames.Count -lt 20) {
        throw "Too few inspection frames were extracted: $($ExtractedFrames.Count)"
    }

    $FrameMetadata = [ordered]@{
        inspection_id = $InspectionId
        video_path = $VideoPath
        video_sha256 = $VideoHash
        fps = $Fps
        extracted_frames = $ExtractedFrames.Count
        completed_at = (Get-Date).ToString("o")
    }

    $FrameMetadata |
        ConvertTo-Json -Depth 10 |
        Set-Content `
            -LiteralPath $FrameMetadataPath `
            -Encoding UTF8
}
else {
    Write-Stage "1 / 6 - Reuse verified inspection frames"
}

$InspectionFrames = @(
    Get-ChildItem `
        -LiteralPath $FramesDir `
        -File |
    Where-Object {
        $_.Extension.ToLower() -in @(
            ".jpg",
            ".jpeg",
            ".png"
        )
    } |
    Sort-Object Name
)

if ($InspectionFrames.Count -eq 0) {
    throw "No inspection frames are available."
}

Write-Host "Inspection frames: $($InspectionFrames.Count)"


# ------------------------------------------------------------
# 2. Prepare isolated COLMAP workspace
# ------------------------------------------------------------

Write-Stage "2 / 6 - Prepare isolated COLMAP workspace"

Copy-Item `
    -LiteralPath $BaselineDatabase `
    -Destination $WorkDatabase `
    -Force

Copy-Item `
    -Path (
        Join-Path $BaselineModel "*"
    ) `
    -Destination $InputModel `
    -Recurse `
    -Force

$CameraLine = Get-Content `
    -LiteralPath $BaselinePoseText |
Where-Object {
    $_ -and (-not $_.StartsWith("#"))
} |
Select-Object -First 1

if (-not $CameraLine) {
    throw "No camera record found in: $BaselinePoseText"
}

$CameraId = [int](
    $CameraLine.Trim().Split(
        [char[]]" `t",
        [System.StringSplitOptions]::RemoveEmptyEntries
    )[0]
)

$ImageNames = New-Object System.Collections.Generic.List[string]

foreach ($Frame in $InspectionFrames) {
    $Destination = Join-Path `
        $WorkInspectionImages `
        $Frame.Name

    New-LinkedFile `
        -Source $Frame.FullName `
        -Destination $Destination

    $ImageNames.Add(
        "inspection/$($Frame.Name)"
    )
}

$ImageNames |
    Set-Content `
        -LiteralPath $ImageListPath `
        -Encoding ASCII

Write-Host "Baseline database : $BaselineDatabase"
Write-Host "Baseline model    : $BaselineModel"
Write-Host "Existing camera ID: $CameraId"
Write-Host "Image list        : $ImageListPath"


# ------------------------------------------------------------
# 3. Extract features for the new inspection images
# ------------------------------------------------------------

Invoke-NativeCommand `
    -StageName "3 / 6 - Extract inspection image features" `
    -Executable $ColmapBat `
    -Arguments @(
        "feature_extractor",
        "--database_path", $WorkDatabase,
        "--image_path", $WorkImages,
        "--image_list_path", $ImageListPath,
        "--ImageReader.existing_camera_id", "$CameraId",
        "--FeatureExtraction.use_gpu", "1"
    ) `
    -LogPath (
        Join-Path $LogsDir "02_feature_extraction.log"
    )


# ------------------------------------------------------------
# 4. Match new images against the baseline database
# ------------------------------------------------------------

Invoke-NativeCommand `
    -StageName "4 / 6 - Match inspection and baseline features" `
    -Executable $ColmapBat `
    -Arguments @(
        "exhaustive_matcher",
        "--database_path", $WorkDatabase,
        "--FeatureMatching.use_gpu", "1"
    ) `
    -LogPath (
        Join-Path $LogsDir "03_exhaustive_matching.log"
    )


# ------------------------------------------------------------
# 5. Register camera poses without bundle adjustment
# ------------------------------------------------------------

Invoke-NativeCommand `
    -StageName "5 / 6 - Register inspection camera poses" `
    -Executable $ColmapBat `
    -Arguments @(
        "image_registrator",
        "--database_path", $WorkDatabase,
        "--input_path", $InputModel,
        "--output_path", $RegisteredModel
    ) `
    -LogPath (
        Join-Path $LogsDir "04_image_registrator.log"
    )

Invoke-NativeCommand `
    -StageName "Convert registered model to TXT" `
    -Executable $ColmapBat `
    -Arguments @(
        "model_converter",
        "--input_path", $RegisteredModel,
        "--output_path", $ModelTextDir,
        "--output_type", "TXT"
    ) `
    -LogPath (
        Join-Path $LogsDir "05_model_converter.log"
    )


# ------------------------------------------------------------
# 6. Analyze registration and write summary
# ------------------------------------------------------------

$Stopwatch.Stop()

$ImagesText = Join-Path $ModelTextDir "images.txt"

if (-not (Test-Path -LiteralPath $ImagesText -PathType Leaf)) {
    throw "Registered images.txt not found: $ImagesText"
}

Invoke-NativeCommand `
    -StageName "6 / 6 - Analyze registration coverage" `
    -Executable $PythonExe `
    -Arguments @(
        $AnalyzerScript,
        $ImagesText,
        $FramesDir,
        $ReportsDir,
        $InspectionId,
        $BaselineId,
        $WorkDatabase,
        $RegisteredModel,
        "$($Stopwatch.Elapsed.TotalSeconds)"
    ) `
    -LogPath (
        Join-Path $LogsDir "06_registration_analysis.log"
    )

if (-not (Test-Path -LiteralPath $SummaryPath -PathType Leaf)) {
    throw "Localization summary was not created: $SummaryPath"
}

$Summary = Get-Content `
    -LiteralPath $SummaryPath `
    -Raw |
ConvertFrom-Json

if (
    ($Summary.status -ne "ready") -or
    ([int]$Summary.registered_frames -le 0)
) {
    throw "No inspection frames were registered."
}

Write-Stage "[PASS] INSPECTION LOCALIZATION COMPLETED"
Write-Host "Inspection         : $InspectionId"
Write-Host "Baseline           : $BaselineId"
Write-Host "Input frames       : $($Summary.input_frames)"
Write-Host "Registered frames  : $($Summary.registered_frames)"
Write-Host "Registration rate  : $($Summary.registration_rate_percent)%"
Write-Host "Registered model   : $RegisteredModel"
Write-Host "Summary            : $SummaryPath"
