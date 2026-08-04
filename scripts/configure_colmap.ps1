#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$ColmapBat
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$ColmapBat = [System.IO.Path]::GetFullPath($ColmapBat)
$ScriptsRoot = Join-Path $ProjectRoot "shared\scripts"

if (-not (Test-Path -LiteralPath $ColmapBat -PathType Leaf)) {
    throw "COLMAP launcher not found: $ColmapBat"
}

$Targets = @(
    (Join-Path $ScriptsRoot "run_baseline_pipeline.ps1"),
    (Join-Path $ScriptsRoot "run_inspection_localization.ps1")
)

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

foreach ($Path in $Targets) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Pipeline script not found: $Path"
    }

    $Text = Get-Content -LiteralPath $Path -Raw
    $Pattern = '\[string\]\$ColmapBat\s*=\s*"[^"]+"'
    $Regex = [regex]::new($Pattern)
    $Match = $Regex.Match($Text)

    if (-not $Match.Success) {
        throw "Default ColmapBat assignment not found: $Path"
    }

    $Replacement = '[string]$ColmapBat = "' + $ColmapBat + '"'

    if ($Match.Value -eq $Replacement) {
        Write-Host "[PASS] COLMAP already configured: $Path"
        continue
    }

    $Evaluator = [System.Text.RegularExpressions.MatchEvaluator]{
        param($CurrentMatch)
        return $Replacement
    }
    $Updated = $Regex.Replace($Text, $Evaluator, 1)

    Copy-Item -LiteralPath $Path -Destination "$Path.before_colmap_config_$Timestamp" -Force
    Set-Content -LiteralPath $Path -Value $Updated -Encoding UTF8
    Write-Host "[UPDATED] $Path"
}

$ConfigRoot = Join-Path $ProjectRoot "shared\config"
New-Item -ItemType Directory -Force -Path $ConfigRoot | Out-Null

[ordered]@{
    colmap_path = $ColmapBat
    colmap_release = "4.1.1"
    configured_at = (Get-Date).ToString("o")
} |
    ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $ConfigRoot "colmap_config.json") -Encoding UTF8

Write-Host "[PASS] COLMAP configured: $ColmapBat"
