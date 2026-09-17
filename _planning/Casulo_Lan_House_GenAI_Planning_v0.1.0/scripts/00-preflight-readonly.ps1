[CmdletBinding()]
param(
    [string]$Root = 'C:\Users\guimo\Downloads\ex'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

function Write-Section([string]$Title) {
    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
}

function Show-CommandVersion([string]$Name, [string[]]$Arguments = @('--version')) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        [pscustomobject]@{ Tool = $Name; Present = $false; Version = $null }
        return
    }
    $versionText = try { (& $Name @Arguments 2>&1 | Select-Object -First 1).ToString() } catch { $_.Exception.Message }
    [pscustomobject]@{ Tool = $Name; Present = $true; Version = $versionText }
}

Write-Host 'CASULO STAGE ZERO PREFLIGHT — READ ONLY' -ForegroundColor Green
Write-Host "Root: $Root"
Write-Host 'This script does not install, delete, initialize Git, or change configuration.'

Write-Section 'Root'
if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    Write-Error "Root does not exist: $Root"
    exit 2
}
Get-Item -LiteralPath $Root | Select-Object FullName, CreationTime, LastWriteTime

Write-Section 'Host'
Get-CimInstance Win32_Processor |
    Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed
Get-CimInstance Win32_ComputerSystem |
    Select-Object Manufacturer, Model, @{N='RAM_GB';E={[math]::Round($_.TotalPhysicalMemory / 1GB, 2)}}
Get-CimInstance Win32_VideoController |
    Select-Object Name, DriverVersion, @{N='Reported_VRAM_GB';E={[math]::Round($_.AdapterRAM / 1GB, 2)}}
Get-ComputerInfo |
    Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, HyperVisorPresent

Write-Section 'Storage'
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
    Select-Object DeviceID,
        @{N='Total_GB';E={[math]::Round($_.Size / 1GB, 2)}},
        @{N='Free_GB';E={[math]::Round($_.FreeSpace / 1GB, 2)}}

Write-Section 'Inventory'
$files = @(Get-ChildItem -LiteralPath $Root -Recurse -Force -File -ErrorAction SilentlyContinue)
$totalBytes = ($files | Measure-Object Length -Sum).Sum
[pscustomobject]@{
    Files = $files.Count
    Total_GB = [math]::Round(($totalBytes / 1GB), 3)
}

Write-Section 'Files >= 100 MB'
$largeFiles = @($files | Where-Object Length -ge 100MB | Sort-Object Length -Descending)
if ($largeFiles.Count -eq 0) {
    Write-Host 'None'
} else {
    $largeFiles | Select-Object @{N='Size_MB';E={[math]::Round($_.Length / 1MB, 2)}}, FullName
}

Write-Section 'Nested Git directories'
$gitDirs = @(Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -Filter '.git' -ErrorAction SilentlyContinue)
if ($gitDirs.Count -eq 0) { Write-Host 'None' } else { $gitDirs | Select-Object FullName }

Write-Section 'Suspicious secret-bearing filenames only'
$secretNames = @($files | Where-Object {
    $_.Name -match '(^\.env($|\.)|credential|secret|private.*key|id_rsa|id_ed25519|\.pfx$|\.p12$|\.pem$)'
})
if ($secretNames.Count -eq 0) { Write-Host 'None detected by filename heuristic' } else { $secretNames | Select-Object FullName }

Write-Section 'Toolchain'
@(
    Show-CommandVersion git
    Show-CommandVersion git @('lfs', 'version')
    Show-CommandVersion pwsh
    Show-CommandVersion winget
    Show-CommandVersion cmake
    Show-CommandVersion ninja
    Show-CommandVersion clang
    Show-CommandVersion rustc
    Show-CommandVersion cargo
    Show-CommandVersion python
    Show-CommandVersion node
    Show-CommandVersion ffmpeg @('-version')
    Show-CommandVersion rg
) | Format-Table -AutoSize

Write-Section 'WSL'
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    & wsl.exe --status 2>&1
    & wsl.exe --version 2>&1
    & wsl.exe --list --verbose 2>&1
} else {
    Write-Host 'wsl.exe not found'
}

Write-Section 'Reserved ports'
$reservedPorts = 8443, 8081, 8082, 8083, 8084
$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object LocalPort -in $reservedPorts |
    Select-Object LocalAddress, LocalPort, OwningProcess)
if ($listeners.Count -eq 0) { Write-Host 'Reserved ports are free' } else { $listeners | Format-Table -AutoSize }

Write-Section 'Result'
$cDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$freeGB = if ($cDrive) { [math]::Round($cDrive.FreeSpace / 1GB, 2) } else { 0 }
if ($freeGB -lt 100) {
    Write-Warning "Free space is $freeGB GB; operational target is >= 100 GB."
} else {
    Write-Host "PASS storage: $freeGB GB free" -ForegroundColor Green
}
Write-Host 'Preflight complete. No changes were made.' -ForegroundColor Green

