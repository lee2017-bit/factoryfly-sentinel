param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$InspectionId,

    [Parameter(Mandatory = $true)]
    [string]$BaselineId,

    [int]$TopK = 5,

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


$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$PythonExe = Resolve-Executable `
    -Value $PythonExe `
    -DisplayName "Python"

if ($TopK -lt 1) {
    throw "TopK must be at least 1."
}

$InspectionRoot = Join-Path $ProjectRoot $InspectionId
$BaselineRoot = Join-Path (
    Join-Path $ProjectRoot "baseline"
) $BaselineId

$LocalizationRoot = Join-Path (
    Join-Path (
        Join-Path $InspectionRoot "localization"
    ) $BaselineId
) "reports"

$LocalizationSummaryPath = Join-Path `
    $LocalizationRoot `
    "localization_summary.json"

$BaselineSummaryPath = Join-Path (
    Join-Path $BaselineRoot "reports"
) "baseline_summary.json"

$ScriptRoot = Join-Path $ProjectRoot "shared\scripts"
$CandidateScript = Join-Path `
    $ScriptRoot `
    "generate_pose_candidates.py"
$RefinementScript = Join-Path `
    $ScriptRoot `
    "refine_pose_pairs.py"

foreach ($RequiredPath in @(
    $LocalizationSummaryPath,
    $BaselineSummaryPath,
    $CandidateScript,
    $RefinementScript
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required input not found: $RequiredPath"
    }
}

$LocalizationSummary = Get-Content `
    -LiteralPath $LocalizationSummaryPath `
    -Raw |
ConvertFrom-Json

$BaselineSummary = Get-Content `
    -LiteralPath $BaselineSummaryPath `
    -Raw |
ConvertFrom-Json

if ($LocalizationSummary.status -ne "ready") {
    throw "Localization summary status is not ready."
}

if ($LocalizationSummary.inspection_id -ne $InspectionId) {
    throw "Localization inspection mismatch."
}

if ($LocalizationSummary.baseline_id -ne $BaselineId) {
    throw "Localization baseline mismatch."
}

if ($BaselineSummary.status -ne "ready") {
    throw "Baseline summary status is not ready."
}

$BaselinePoseCsv = [string]$LocalizationSummary.baseline_pose_csv
$InspectionPoseCsv = [string]$LocalizationSummary.inspection_pose_csv
$InspectionFrames = [string]$LocalizationSummary.frame_path
$BaselineFrames = [string]$BaselineSummary.frame_path

foreach ($RequiredPath in @(
    $BaselinePoseCsv,
    $InspectionPoseCsv,
    $InspectionFrames,
    $BaselineFrames
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required data path not found: $RequiredPath"
    }
}

$OutputRoot = Join-Path (
    Join-Path (
        Join-Path $InspectionRoot "change_detection"
    ) $BaselineId
) "pair_refinement"

$LogsDir = Join-Path $OutputRoot "logs"
$PreviewRoot = Join-Path $OutputRoot "previews"
$CandidateCsv = Join-Path $OutputRoot "pose_candidates_topk.csv"
$PoseSummaryPath = Join-Path `
    $OutputRoot `
    "pose_candidate_summary.json"
$RefinementSummaryPath = Join-Path `
    $OutputRoot `
    "refinement_summary.json"

if (
    (Test-Path -LiteralPath $RefinementSummaryPath -PathType Leaf) -and
    (-not $Force)
) {
    throw "A completed pair refinement already exists. Use -Force to overwrite: $RefinementSummaryPath"
}

if ($Force -and (Test-Path -LiteralPath $OutputRoot)) {
    Write-Stage "Cleaning previous pair-refinement output"

    Remove-Item `
        -LiteralPath $OutputRoot `
        -Recurse `
        -Force
}

foreach ($Directory in @(
    $OutputRoot,
    $LogsDir,
    $PreviewRoot
)) {
    New-Item `
        -ItemType Directory `
        -Force `
        -Path $Directory |
    Out-Null
}

$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Invoke-NativeCommand `
    -StageName "1 / 2 - Generate Top-K pose candidates" `
    -Executable $PythonExe `
    -Arguments @(
        $CandidateScript,
        $BaselinePoseCsv,
        $InspectionPoseCsv,
        $CandidateCsv,
        "$TopK",
        $PoseSummaryPath
    ) `
    -LogPath (
        Join-Path $LogsDir "01_pose_candidates.log"
    )

Invoke-NativeCommand `
    -StageName "2 / 2 - Geometric pair refinement" `
    -Executable $PythonExe `
    -Arguments @(
        $RefinementScript,
        $CandidateCsv,
        $BaselineFrames,
        $InspectionFrames,
        $OutputRoot,
        $PreviewRoot,
        $InspectionId,
        $BaselineId
    ) `
    -LogPath (
        Join-Path $LogsDir "02_geometric_refinement.log"
    )

$Stopwatch.Stop()

if (-not (Test-Path -LiteralPath $RefinementSummaryPath -PathType Leaf)) {
    throw "Refinement summary was not created: $RefinementSummaryPath"
}

$Summary = Get-Content `
    -LiteralPath $RefinementSummaryPath `
    -Raw |
ConvertFrom-Json

$Summary.duration_seconds = [math]::Round(
    $Stopwatch.Elapsed.TotalSeconds,
    2
)

$Summary |
    ConvertTo-Json -Depth 20 |
    Set-Content `
        -LiteralPath $RefinementSummaryPath `
        -Encoding UTF8

if (
    ($Summary.status -ne "ready") -or
    ([int]$Summary.evaluated_candidates -le 0)
) {
    throw "Pair refinement produced no valid result."
}

Write-Stage "[PASS] PAIR REFINEMENT COMPLETED"
Write-Host "Inspection          : $InspectionId"
Write-Host "Baseline            : $BaselineId"
Write-Host "Inspection frames   : $($Summary.inspection_frames)"
Write-Host "Candidates evaluated: $($Summary.evaluated_candidates)"
Write-Host "AMD-ready pairs     : $($Summary.amd_ready_pairs)"
Write-Host "Summary             : $RefinementSummaryPath"
