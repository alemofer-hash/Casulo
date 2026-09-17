[CmdletBinding()]
param(
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$packages = @(
    @{ Id = 'Microsoft.PowerShell'; Name = 'PowerShell 7' },
    @{ Id = 'Git.Git'; Name = 'Git for Windows' },
    @{ Id = 'GitHub.GitLFS'; Name = 'Git LFS' },
    @{ Id = 'Kitware.CMake'; Name = 'CMake' },
    @{ Id = 'Ninja-build.Ninja'; Name = 'Ninja' },
    @{ Id = 'LLVM.LLVM'; Name = 'LLVM/Clang' },
    @{ Id = 'Rustlang.Rustup'; Name = 'Rustup' },
    @{ Id = 'Python.Python.3.12'; Name = 'Python 3.12' },
    @{ Id = 'OpenJS.NodeJS.LTS'; Name = 'Node.js LTS' },
    @{ Id = 'Gyan.FFmpeg'; Name = 'FFmpeg' },
    @{ Id = 'FiloSottile.mkcert'; Name = 'mkcert' },
    @{ Id = 'AquaSecurity.Trivy'; Name = 'Trivy' },
    @{ Id = 'Microsoft.VisualStudioCode'; Name = 'Visual Studio Code' }
)

Write-Host 'CASULO WINDOWS CORE INSTALLER' -ForegroundColor Cyan
Write-Host 'Default mode is plan-only. -Apply performs WinGet installs.'

if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
    throw 'WinGet is unavailable. Install/update Microsoft App Installer from an official Microsoft source.'
}

foreach ($package in $packages) {
    Write-Host ("{0} [{1}]" -f $package.Name, $package.Id)
}

Write-Host 'Visual Studio Build Tools 2022 with the C++ workload is also mandatory.'
Write-Host 'WSL2 + Ubuntu 24.04 is mandatory and is deliberately installed separately because it may require restart.'
Write-Host 'Intel/OEM graphics drivers and Vulkan capability must be validated manually.'

if (-not $Apply) {
    Write-Host "`nDRY RUN complete. Re-run as Administrator with -Apply to install the WinGet package set." -ForegroundColor Yellow
    exit 0
}

foreach ($package in $packages) {
    & winget.exe list --id $package.Id --exact --accept-source-agreements | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Already present: $($package.Id)" -ForegroundColor DarkGreen
        continue
    }
    & winget.exe install --id $package.Id --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Installation failed: $($package.Id)"
    }
}

$buildToolsId = 'Microsoft.VisualStudio.2022.BuildTools'
& winget.exe list --id $buildToolsId --exact --accept-source-agreements | Out-Null
if ($LASTEXITCODE -ne 0) {
    & winget.exe install --id $buildToolsId --exact `
        --accept-package-agreements --accept-source-agreements `
        --override '--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'
    if ($LASTEXITCODE -ne 0) { throw 'Visual Studio Build Tools installation failed.' }
} else {
    Write-Host 'Visual Studio Build Tools already present; verify the C++ workload in Visual Studio Installer.' -ForegroundColor Yellow
}

Write-Host "`nCore Windows package installation complete." -ForegroundColor Green
Write-Host 'Next deliberate administrator action:'
Write-Host '  wsl --install -d Ubuntu-24.04'
Write-Host 'Restart if requested, initialize Ubuntu, then run 03-install-wsl-core.sh --apply inside WSL.'
