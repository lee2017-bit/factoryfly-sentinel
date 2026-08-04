#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $ProjectRoot "start_factoryfly.bat"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "FactoryFly Sentinel.lnk"

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
    throw "Launcher not found: $Launcher"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Launch FactoryFly Sentinel"
$Shortcut.WindowStyle = 1
$Shortcut.Save()

Write-Host "[PASS] Desktop shortcut created: $ShortcutPath"
