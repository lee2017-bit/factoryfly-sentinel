param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$InspectionId,

    [Parameter(Mandatory = $true)]
    [string]$BaselineId,

    [ValidateSet("package", "cloud")]
    [string]$Mode = "package",

    [string]$ManualFrames = "",

    [int]$BatchPairs = 2,

    [string]$PythonExe = "python",

    [string]$HostName = "",

    [int]$Port = 22,

    [string]$UserName = "root",

    [string]$KeyPath = "",

    [string]$RemoteRoot = "/workspace/factoryfly-radeon",

    [string]$RemotePython = "/workspace/factoryfly-radeon/.venv-rocm/bin/python",

    [string]$DinoRepo = "/workspace/factoryfly-radeon/vendor/dinov2",

    [string]$Checkpoint = "/workspace/factoryfly-radeon/vendor/checkpoints/dinov2_vits14_pretrain.pth",

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# FactoryFly v7.3.9b: allow automatic-only AMD runs
# Invoke-NativeCommand requires non-empty native arguments. A delimiter-only
# value is parsed by prepare_amd_package.py as an empty manual-frame set.
if ([string]::IsNullOrWhiteSpace($ManualFrames)) {
    $ManualFrames = ","
}



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


function ConvertTo-BashLiteral {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return "'" + ($Value -replace "'", "'""'""'") + "'"
}


$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$PythonExe = Resolve-Executable `
    -Value $PythonExe `
    -DisplayName "Python"

$InspectionRoot = Join-Path $ProjectRoot $InspectionId
$BaselineRoot = Join-Path (
    Join-Path $ProjectRoot "baseline"
) $BaselineId
$PairRoot = Join-Path (
    Join-Path (
        Join-Path $InspectionRoot "change_detection"
    ) $BaselineId
) "pair_refinement"
$PairSummaryPath = Join-Path $PairRoot "refinement_summary.json"
$BaselineSummaryPath = Join-Path (
    Join-Path $BaselineRoot "reports"
) "baseline_summary.json"
$RefinedPairsPath = Join-Path $PairRoot "refined_pairs.csv"

$ScriptRoot = Join-Path $ProjectRoot "shared\scripts"
$PackageScript = Join-Path $ScriptRoot "prepare_amd_package.py"
$RemoteScript = Join-Path $ScriptRoot "run_amd_dino_analysis.py"

foreach ($RequiredPath in @(
    $PairSummaryPath,
    $BaselineSummaryPath,
    $RefinedPairsPath,
    $PackageScript,
    $RemoteScript
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required input not found: $RequiredPath"
    }
}

$PairSummary = Get-Content `
    -LiteralPath $PairSummaryPath `
    -Raw |
ConvertFrom-Json

$BaselineSummary = Get-Content `
    -LiteralPath $BaselineSummaryPath `
    -Raw |
ConvertFrom-Json

if ($PairSummary.status -ne "ready") {
    throw "Pair refinement status is not ready."
}

if ($PairSummary.inspection_id -ne $InspectionId) {
    throw "Pair refinement inspection mismatch."
}

if ($PairSummary.baseline_id -ne $BaselineId) {
    throw "Pair refinement baseline mismatch."
}

if ($BaselineSummary.status -ne "ready") {
    throw "Baseline summary status is not ready."
}

$BaselineFrames = [string]$BaselineSummary.frame_path
$InspectionFrames = Join-Path (
    Join-Path $InspectionRoot "frames"
) "raw"

foreach ($RequiredPath in @(
    $BaselineFrames,
    $InspectionFrames
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Container)) {
        throw "Frame directory not found: $RequiredPath"
    }
}

$AnalysisRoot = Join-Path (
    Join-Path (
        Join-Path $InspectionRoot "change_detection"
    ) $BaselineId
) "amd_analysis\current"
$PackageDir = Join-Path $AnalysisRoot "package"
$PackageZip = Join-Path $AnalysisRoot "factoryfly_amd_package.zip"
$ResultsDir = Join-Path $AnalysisRoot "results"
$LogsDir = Join-Path $AnalysisRoot "logs"
$DownloadedZip = Join-Path $AnalysisRoot "amd_results.zip"
$RunSummaryPath = Join-Path $AnalysisRoot "amd_run_summary.json"

if ($Force -and (Test-Path -LiteralPath $AnalysisRoot)) {
    Write-Stage "Cleaning current AMD analysis workspace"

    Remove-Item `
        -LiteralPath $AnalysisRoot `
        -Recurse `
        -Force
}

if (
    (Test-Path -LiteralPath $RunSummaryPath -PathType Leaf) -and
    (-not $Force)
) {
    $ExistingSummary = Get-Content `
        -LiteralPath $RunSummaryPath `
        -Raw |
    ConvertFrom-Json

    if ($ExistingSummary.status -eq "ready") {
        throw "A completed AMD analysis already exists. Use -Force to overwrite."
    }
}

foreach ($Directory in @(
    $AnalysisRoot,
    $LogsDir
)) {
    New-Item `
        -ItemType Directory `
        -Force `
        -Path $Directory |
    Out-Null
}

Invoke-NativeCommand `
    -StageName "1 / 4 - Prepare privacy-filtered AMD package" `
    -Executable $PythonExe `
    -Arguments @(
        $PackageScript,
        $RefinedPairsPath,
        $BaselineFrames,
        $InspectionFrames,
        $PackageDir,
        $PackageZip,
        $ManualFrames,
        $RemoteScript,
        $InspectionId,
        $BaselineId
    ) `
    -LogPath (
        Join-Path $LogsDir "01_prepare_package.log"
    )

$PackageSummaryPath = Join-Path $PackageDir "package_summary.json"
$PackageSummary = Get-Content `
    -LiteralPath $PackageSummaryPath `
    -Raw |
ConvertFrom-Json

if ($Mode -eq "package") {
    $PackageRunSummary = [ordered]@{
        inspection_id = $InspectionId
        baseline_id = $BaselineId
        status = "package_ready"
        completed_at = (Get-Date).ToString("o")
        analyzed_pairs = 0
        package_pairs = [int]$PackageSummary.selected_pairs
        package_root = $PackageDir
        package_zip = $PackageZip
        result_root = ""
        result_summary_path = ""
        benchmark_path = ""
        scores_csv_path = ""
    }

    $PackageRunSummary |
        ConvertTo-Json -Depth 20 |
        Set-Content `
            -LiteralPath $RunSummaryPath `
            -Encoding UTF8

    Write-Stage "[PASS] AMD PACKAGE READY"
    Write-Host "Selected pairs : $($PackageSummary.selected_pairs)"
    Write-Host "Archive        : $PackageZip"
    exit 0
}

if ([string]::IsNullOrWhiteSpace($HostName)) {
    throw "SSH host is required for cloud mode."
}

if ([string]::IsNullOrWhiteSpace($UserName)) {
    throw "SSH user is required for cloud mode."
}

if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "SSH private key not found: $KeyPath"
}

$SshExe = Resolve-Executable `
    -Value "ssh" `
    -DisplayName "OpenSSH ssh"
$ScpExe = Resolve-Executable `
    -Value "scp" `
    -DisplayName "OpenSSH scp"

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RemoteRun = "$RemoteRoot/factoryfly_runs/$InspectionId-$BaselineId-$Timestamp"
$RemotePackageZip = "$RemoteRun/factoryfly_amd_package.zip"
$RemotePackageDir = "$RemoteRun/package"
$RemoteOutputDir = "$RemoteRun/results"
$RemoteResultZip = "$RemoteRun/amd_results.zip"
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

$PrepareSshArguments = @()
$PrepareSshArguments += $CommonSshArguments
$PrepareSshArguments += @(
    $Target,
    "mkdir -p $(ConvertTo-BashLiteral $RemoteRun)"
)

Invoke-NativeCommand `
    -StageName "2 / 4 - Create Radeon Cloud run directory" `
    -Executable $SshExe `
    -Arguments $PrepareSshArguments `
    -LogPath (
        Join-Path $LogsDir "02_ssh_prepare.log"
    )

Invoke-NativeCommand `
    -StageName "3 / 4 - Upload and execute AMD DINOv2 analysis" `
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
    -LogPath (
        Join-Path $LogsDir "03_scp_upload.log"
    )

$QuotedRemotePython = ConvertTo-BashLiteral $RemotePython
$QuotedRemotePackageZip = ConvertTo-BashLiteral $RemotePackageZip
$QuotedRemotePackageDir = ConvertTo-BashLiteral $RemotePackageDir
$QuotedRemoteOutputDir = ConvertTo-BashLiteral $RemoteOutputDir
$QuotedRemoteResultZip = ConvertTo-BashLiteral $RemoteResultZip
$QuotedDinoRepo = ConvertTo-BashLiteral $DinoRepo
$QuotedCheckpoint = ConvertTo-BashLiteral $Checkpoint
$RemoteAnalysisScript = "$RemotePackageDir/run_amd_dino_analysis.py"
$QuotedRemoteAnalysisScript = ConvertTo-BashLiteral $RemoteAnalysisScript

$RemoteCommandParts = @(
    "set -e;"
    "$QuotedRemotePython -m zipfile -e $QuotedRemotePackageZip $QuotedRemotePackageDir;"
    "$QuotedRemotePython $QuotedRemoteAnalysisScript --package-dir $QuotedRemotePackageDir --output-dir $QuotedRemoteOutputDir --result-zip $QuotedRemoteResultZip --dinov2-repo $QuotedDinoRepo --checkpoint $QuotedCheckpoint --batch-pairs $BatchPairs"
)
$RemoteCommand = $RemoteCommandParts -join " "

$AnalysisSshArguments = @()
$AnalysisSshArguments += $CommonSshArguments
$AnalysisSshArguments += @(
    $Target,
    $RemoteCommand
)

Invoke-NativeCommand `
    -StageName "Run ROCm DINOv2 on Radeon Cloud" `
    -Executable $SshExe `
    -Arguments $AnalysisSshArguments `
    -LogPath (
        Join-Path $LogsDir "04_remote_analysis.log"
    )

if (Test-Path -LiteralPath $DownloadedZip) {
    Remove-Item `
        -LiteralPath $DownloadedZip `
        -Force
}

Invoke-NativeCommand `
    -StageName "4 / 4 - Download AMD results" `
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
    -LogPath (
        Join-Path $LogsDir "05_scp_download.log"
    )

if (Test-Path -LiteralPath $ResultsDir) {
    Remove-Item `
        -LiteralPath $ResultsDir `
        -Recurse `
        -Force
}

New-Item `
    -ItemType Directory `
    -Force `
    -Path $ResultsDir |
Out-Null

Expand-Archive `
    -LiteralPath $DownloadedZip `
    -DestinationPath $ResultsDir `
    -Force

$ResultSummaryPath = Join-Path $ResultsDir "run_summary.json"
$BenchmarkPath = Join-Path $ResultsDir "amd_benchmark.json"
$ScoresPath = Join-Path $ResultsDir "scores.csv"

foreach ($RequiredPath in @(
    $ResultSummaryPath,
    $BenchmarkPath,
    $ScoresPath
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Downloaded result is incomplete: $RequiredPath"
    }
}

$ResultSummary = Get-Content `
    -LiteralPath $ResultSummaryPath `
    -Raw |
ConvertFrom-Json

$RunSummary = [ordered]@{
    inspection_id = $InspectionId
    baseline_id = $BaselineId
    status = "ready"
    completed_at = (Get-Date).ToString("o")
    analyzed_pairs = [int]$ResultSummary.analyzed_pairs
    package_pairs = [int]$PackageSummary.selected_pairs
    package_root = $PackageDir
    package_zip = $PackageZip
    result_root = $ResultsDir
    result_summary_path = $ResultSummaryPath
    benchmark_path = $BenchmarkPath
    scores_csv_path = $ScoresPath
    remote_run_directory = $RemoteRun
    remote_host = $HostName
    remote_user = $UserName
    remote_port = $Port
}

$RunSummary |
    ConvertTo-Json -Depth 20 |
    Set-Content `
        -LiteralPath $RunSummaryPath `
        -Encoding UTF8

Write-Stage "[PASS] AMD CLOUD ANALYSIS COMPLETED"
Write-Host "Analyzed pairs : $($RunSummary.analyzed_pairs)"
Write-Host "Remote run     : $RemoteRun"
Write-Host "Local results  : $ResultsDir"
