#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ColmapBat = "C:\Tools\COLMAP\COLMAP.bat"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$VenvRoot = Join-Path $ProjectRoot ".venv-vision"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements-local.txt"

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    $Py = Get-Command py.exe -ErrorAction SilentlyContinue

    if ($null -ne $Py) {
        & $Py.Source -3.12 -m venv $VenvRoot
        if ($LASTEXITCODE -ne 0) {
            & $Py.Source -3 -m venv $VenvRoot
        }
    }
    else {
        $Python = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -eq $Python) {
            throw "Python was not found. Install Python 3.12 or later."
        }
        & $Python.Source -m venv $VenvRoot
    }
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    throw "Virtual environment creation failed: $VenvPython"
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -r $Requirements

foreach ($Name in @("ffmpeg.exe", "ssh.exe", "scp.exe")) {
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        throw "Required command not found: $Name"
    }
    Write-Host "[PASS] $Name -> $($Command.Source)"
}

powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $PSScriptRoot "configure_colmap.ps1") `
    -ProjectRoot $ProjectRoot `
    -ColmapBat $ColmapBat

if ($LASTEXITCODE -ne 0) {
    throw "COLMAP configuration failed."
}

& $VenvPython -m py_compile (Join-Path $ProjectRoot "app.py")
if ($LASTEXITCODE -ne 0) {
    throw "app.py syntax validation failed."
}
& $VenvPython -c "import streamlit, cv2, numpy, PIL; print('[PASS] Python imports ready')"

Write-Host ""
Write-Host "============================================================"
Write-Host "[PASS] FactoryFly local environment ready"
Write-Host "Project : $ProjectRoot"
Write-Host "Launch  : $ProjectRoot\start_factoryfly.bat"
Write-Host "============================================================"
