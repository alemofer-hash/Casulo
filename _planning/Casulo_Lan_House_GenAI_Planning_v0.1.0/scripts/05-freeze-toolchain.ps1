[CmdletBinding()]
param(
    [string]$Output = '.\manifests\toolchain.lock.generated.json',
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

function Capture([string]$Name, [string[]]$Arguments = @('--version')) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) { return [ordered]@{ present = $false; path = $null; version = $null } }
    $value = try { ((& $Name @Arguments 2>&1 | Select-Object -First 1).ToString()) } catch { $_.Exception.Message }
    return [ordered]@{ present = $true; path = $command.Source; version = $value }
}

$lock = [ordered]@{
    schema_version = 1
    generated_utc = [DateTime]::UtcNow.ToString('o')
    host = [ordered]@{
        computer = $env:COMPUTERNAME
        windows = (Get-CimInstance Win32_OperatingSystem).Caption
        build = (Get-CimInstance Win32_OperatingSystem).BuildNumber
    }
    tools = [ordered]@{
        git = Capture git
        git_lfs = Capture git @('lfs', 'version')
        powershell = Capture pwsh
        cmake = Capture cmake
        ninja = Capture ninja
        clang = Capture clang
        rustc = Capture rustc
        cargo = Capture cargo
        python = Capture python
        node = Capture node
        npm = Capture npm
        ffmpeg = Capture ffmpeg @('-version')
        ripgrep = Capture rg
        wsl = Capture wsl @('--version')
    }
}

$json = $lock | ConvertTo-Json -Depth 8
if (-not $Apply) {
    $json
    Write-Host "`nDRY RUN: pass -Apply to write $Output" -ForegroundColor Yellow
    exit 0
}

$parent = Split-Path -Parent $Output
if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$json | Set-Content -LiteralPath $Output -Encoding utf8
Write-Host "Toolchain lock written: $Output" -ForegroundColor Green

