param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$InspectionId,

    [Parameter(Mandatory = $true)]
    [string]$BaselineId,

    [Parameter(Mandatory = $true)]
    [string]$MissionId,

    [Parameter(Mandatory = $true)]
    [string]$SourcePath,

    [int]$BatchPairs = 1,

    [string]$PythonExe = "python",

    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [int]$Port = 22,

    [string]$UserName = "root",

    [Parameter(Mandatory = $true)]
    [string]$KeyPath,

    [string]$RemoteRoot = "/workspace/factoryfly-radeon",

    [string]$RemotePython = "/workspace/factoryfly-radeon/.venv-rocm/bin/python",

    [string]$DinoRepo = "/workspace/factoryfly-radeon/vendor/dinov2",

    [string]$Checkpoint = "/workspace/factoryfly-radeon/vendor/checkpoints/dinov2_vits14_pretrain.pth",

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Stage {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Message
    Write-Host "============================================================"
}

function Resolve-Executable {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$DisplayName
    )

    if (Test-Path -LiteralPath $Value -PathType Leaf) {
        return (Get-Item -LiteralPath $Value).FullName
    }

    $Command = Get-Command $Value -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        throw "$DisplayName was not found: $Value"
    }
    return $Command.Source
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$StageName,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogPath
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
            ForEach-Object { $_.ToString() } |
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

function ConvertTo-BashLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + ($Value -replace "'", "'""'""'") + "'"
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$SourcePath = [System.IO.Path]::GetFullPath($SourcePath)
$PythonExe = Resolve-Executable -Value $PythonExe -DisplayName "Python"

if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
    throw "Reinspection source not found: $SourcePath"
}
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "SSH private key not found: $KeyPath"
}

$ScriptRoot = Join-Path $ProjectRoot "shared\scripts"
$PackageScript = Join-Path $ScriptRoot "prepare_reinspection_package.py"
$RemoteScript = Join-Path $ScriptRoot "run_amd_dino_analysis.py"
$InitialAnalysisRoot = Join-Path $ProjectRoot "$InspectionId\change_detection\$BaselineId\amd_analysis\current"
$InitialPackageDir = Join-Path $InitialAnalysisRoot "package"
$MissionRoot = Join-Path $ProjectRoot "$InspectionId\reinspection\$BaselineId\$MissionId"
$MissionJson = Join-Path $MissionRoot "mission.json"
$AnalysisRoot = Join-Path $MissionRoot "analysis\current"
$PackageDir = Join-Path $AnalysisRoot "package"
$PackageZip = Join-Path $AnalysisRoot "factoryfly_reinspection_package.zip"
$ResultsDir = Join-Path $AnalysisRoot "results"
$LogsDir = Join-Path $AnalysisRoot "logs"
$DownloadedZip = Join-Path $AnalysisRoot "reinspection_results.zip"
$RunSummaryPath = Join-Path $AnalysisRoot "reinspection_run_summary.json"

foreach ($RequiredPath in @(
    $PackageScript,
    $RemoteScript,
    $MissionJson,
    (Join-Path $InitialPackageDir "manifest.csv")
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required input not found: $RequiredPath"
    }
}

if ($Force -and (Test-Path -LiteralPath $AnalysisRoot)) {
    Write-Stage "Cleaning current reinspection analysis workspace"
    Remove-Item -LiteralPath $AnalysisRoot -Recurse -Force
}

if ((Test-Path -LiteralPath $RunSummaryPath -PathType Leaf) -and (-not $Force)) {
    $Existing = Get-Content -LiteralPath $RunSummaryPath -Raw | ConvertFrom-Json
    if ($Existing.status -eq "ready") {
        throw "A completed reinspection analysis already exists. Use -Force to overwrite."
    }
}

foreach ($Directory in @($AnalysisRoot, $LogsDir)) {
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
}

Invoke-NativeCommand `
    -StageName "1 / 4 - Prepare targeted reinspection package" `
    -Executable $PythonExe `
    -Arguments @(
        $PackageScript,
        "--initial-package-dir", $InitialPackageDir,
        "--mission-json", $MissionJson,
        "--source", $SourcePath,
        "--package-dir", $PackageDir,
        "--package-zip", $PackageZip,
        "--remote-script", $RemoteScript
    ) `
    -LogPath (Join-Path $LogsDir "01_prepare_package.log")

$PackageSummaryPath = Join-Path $PackageDir "package_summary.json"
$PackageSummary = Get-Content -LiteralPath $PackageSummaryPath -Raw | ConvertFrom-Json

if (($PackageSummary.PSObject.Properties.Name -contains "analysis_required") -and (-not [bool]$PackageSummary.analysis_required)) {
    $RunSummary = [ordered]@{
        inspection_id = $InspectionId
        baseline_id = $BaselineId
        mission_id = $MissionId
        status = "ready"
        outcome = "target_not_reacquired"
        completed_at = (Get-Date).ToString("o")
        source_path = $SourcePath
        source_candidate = [string]$PackageSummary.selected_candidate
        geometry_quality = [string]$PackageSummary.quality
        score_p95 = $null
        score_p99 = $null
        score_mean = $null
        analyzed_pairs = 0
        package_root = $PackageDir
        package_zip = $null
        result_root = $null
        candidate_review_path = (Join-Path $PackageDir "candidate_review.jpg")
        message = [string]$PackageSummary.message
    }
    $RunSummary |
        ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $RunSummaryPath -Encoding UTF8

    Write-Stage "[WARN] TARGETED REINSPECTION DID NOT REACQUIRE THE TARGET"
    Write-Host "Mission          : $MissionId"
    Write-Host "Geometry quality : $($RunSummary.geometry_quality)"
    Write-Host "DINOv2 analysis  : skipped"
    Write-Host "Candidate review : $($RunSummary.candidate_review_path)"
    exit 0
}

$SshExe = Resolve-Executable -Value "ssh" -DisplayName "OpenSSH ssh"
$ScpExe = Resolve-Executable -Value "scp" -DisplayName "OpenSSH scp"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RemoteRun = "$RemoteRoot/factoryfly_reinspection_runs/$InspectionId-$BaselineId-$MissionId-$Timestamp"
$RemotePackageZip = "$RemoteRun/factoryfly_reinspection_package.zip"
$RemotePackageDir = "$RemoteRun/package"
$RemoteOutputDir = "$RemoteRun/results"
$RemoteResultZip = "$RemoteRun/reinspection_results.zip"
$Target = "$UserName@$HostName"

$CommonSshArguments = @(
    "-n",
    "-T",
    "-i", $KeyPath,
    "-p", "$Port",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=20",
    "-o", "ServerAliveInterval=10",
    "-o", "ServerAliveCountMax=2",
    "-o", "StrictHostKeyChecking=accept-new"
)

$PrepareArguments = @()
$PrepareArguments += $CommonSshArguments
$PrepareArguments += @($Target, "mkdir -p $(ConvertTo-BashLiteral $RemoteRun)")

Invoke-NativeCommand `
    -StageName "2 / 4 - Create Radeon Cloud reinspection directory" `
    -Executable $SshExe `
    -Arguments $PrepareArguments `
    -LogPath (Join-Path $LogsDir "02_ssh_prepare.log")

Invoke-NativeCommand `
    -StageName "3 / 4 - Upload reinspection evidence" `
    -Executable $ScpExe `
    -Arguments @(
        "-i", $KeyPath,
        "-P", "$Port",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=20",
        "-o", "StrictHostKeyChecking=accept-new",
        $PackageZip,
        "$Target`:$RemotePackageZip"
    ) `
    -LogPath (Join-Path $LogsDir "03_scp_upload.log")

$QuotedRemotePython = ConvertTo-BashLiteral $RemotePython
$QuotedRemotePackageZip = ConvertTo-BashLiteral $RemotePackageZip
$QuotedRemotePackageDir = ConvertTo-BashLiteral $RemotePackageDir
$QuotedRemoteOutputDir = ConvertTo-BashLiteral $RemoteOutputDir
$QuotedRemoteResultZip = ConvertTo-BashLiteral $RemoteResultZip
$QuotedDinoRepo = ConvertTo-BashLiteral $DinoRepo
$QuotedCheckpoint = ConvertTo-BashLiteral $Checkpoint
$QuotedRemoteAnalysisScript = ConvertTo-BashLiteral "$RemotePackageDir/run_amd_dino_analysis.py"

$RemoteCommand = @(
    "set -e;",
    "$QuotedRemotePython -m zipfile -e $QuotedRemotePackageZip $QuotedRemotePackageDir;",
    "$QuotedRemotePython $QuotedRemoteAnalysisScript --package-dir $QuotedRemotePackageDir --output-dir $QuotedRemoteOutputDir --result-zip $QuotedRemoteResultZip --dinov2-repo $QuotedDinoRepo --checkpoint $QuotedCheckpoint --batch-pairs $BatchPairs"
) -join " "

$AnalysisArguments = @()
$AnalysisArguments += $CommonSshArguments
$AnalysisArguments += @($Target, $RemoteCommand)

Invoke-NativeCommand `
    -StageName "Run ROCm DINOv2 targeted reinspection analysis" `
    -Executable $SshExe `
    -Arguments $AnalysisArguments `
    -LogPath (Join-Path $LogsDir "04_remote_analysis.log")

if (Test-Path -LiteralPath $DownloadedZip) {
    Remove-Item -LiteralPath $DownloadedZip -Force
}

Invoke-NativeCommand `
    -StageName "4 / 4 - Download reinspection results" `
    -Executable $ScpExe `
    -Arguments @(
        "-i", $KeyPath,
        "-P", "$Port",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=20",
        "-o", "StrictHostKeyChecking=accept-new",
        "$Target`:$RemoteResultZip",
        $DownloadedZip
    ) `
    -LogPath (Join-Path $LogsDir "05_scp_download.log")

if (Test-Path -LiteralPath $ResultsDir) {
    Remove-Item -LiteralPath $ResultsDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null
Expand-Archive -LiteralPath $DownloadedZip -DestinationPath $ResultsDir -Force

$ResultSummaryPath = Join-Path $ResultsDir "run_summary.json"
$BenchmarkPath = Join-Path $ResultsDir "amd_benchmark.json"
$ScoresPath = Join-Path $ResultsDir "scores.csv"

foreach ($RequiredPath in @($ResultSummaryPath, $BenchmarkPath, $ScoresPath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Downloaded result is incomplete: $RequiredPath"
    }
}

$ResultSummary = Get-Content -LiteralPath $ResultSummaryPath -Raw | ConvertFrom-Json
$Scores = Import-Csv -LiteralPath $ScoresPath
$Score = $Scores | Select-Object -First 1

$RunSummary = [ordered]@{
    inspection_id = $InspectionId
    baseline_id = $BaselineId
    mission_id = $MissionId
    status = "ready"
    completed_at = (Get-Date).ToString("o")
    source_path = $SourcePath
    source_candidate = [string]$PackageSummary.selected_candidate
    geometry_quality = [string]$PackageSummary.quality
    initial_reference_quality = [string]$PackageSummary.initial_reference_quality
    candidate_review_path = (Join-Path $PackageDir "candidate_review.jpg")
    score_p95 = [double]$Score.score_p95
    score_p99 = [double]$Score.score_p99
    score_mean = [double]$Score.score_mean
    analyzed_pairs = [int]$ResultSummary.analyzed_pairs
    package_root = $PackageDir
    package_zip = $PackageZip
    result_root = $ResultsDir
    result_summary_path = $ResultSummaryPath
    benchmark_path = $BenchmarkPath
    scores_csv_path = $ScoresPath
    montage_path = (Join-Path $ResultsDir ([string]$Score.montage_file))
    overlay_path = (Join-Path $ResultsDir ([string]$Score.overlay_file))
    remote_run_directory = $RemoteRun
}

$RunSummary |
    ConvertTo-Json -Depth 20 |
    Set-Content -LiteralPath $RunSummaryPath -Encoding UTF8

Write-Stage "[PASS] TARGETED REINSPECTION ANALYSIS COMPLETED"
Write-Host "Mission          : $MissionId"
Write-Host "Geometry quality : $($RunSummary.geometry_quality)"
Write-Host "Reinspect p95    : $($RunSummary.score_p95)"
Write-Host "Result root      : $ResultsDir"
