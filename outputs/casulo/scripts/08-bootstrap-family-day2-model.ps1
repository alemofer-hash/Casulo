param(
    [string]$CacheRoot = "$env:LOCALAPPDATA\Casulo\family-rp01\day2",
    [string]$ManifestPath = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path (Split-Path -Parent $PSScriptRoot) "config\family\day2-model-candidates.json"
}

$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
if ($manifest.schema -ne "casulo.family.day2-model-candidates/1.0") {
    throw "Manifest schema mismatch"
}

$minimumFree = [int64]$manifest.minimum_free_bytes
$projectedPeak = [int64](14GB)
$cache = [IO.Path]::GetFullPath($CacheRoot)
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($cache))
if (($drive.AvailableFreeSpace - $projectedPeak) -lt $minimumFree) {
    throw "Projected install would cross the 30 GiB reserve"
}

$downloads = Join-Path $cache "downloads"
$models = Join-Path $cache "models"
$runtimes = Join-Path $cache "runtimes"
$licenses = Join-Path $cache "licenses"
@($cache, $downloads, $models, $runtimes, $licenses) | ForEach-Object {
    New-Item -ItemType Directory -Force -Path $_ | Out-Null
}

function Get-LowerSha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Assert-Asset([string]$Path, [int64]$Bytes, [string]$Sha256) {
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $Bytes) {
        throw "Size mismatch: $Path"
    }
    if ((Get-LowerSha256 $Path) -ne $Sha256) {
        throw "SHA-256 mismatch: $Path"
    }
}

function Receive-VerifiedAsset($Asset, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        Assert-Asset $Destination ([int64]$Asset.bytes) ([string]$Asset.sha256)
        return
    }
    $partial = "$Destination.part"
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    & $curl --fail --location --retry 5 --retry-delay 2 --continue-at - --output $partial ([string]$Asset.url)
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed: $($Asset.url)"
    }
    Assert-Asset $partial ([int64]$Asset.bytes) ([string]$Asset.sha256)
    Move-Item -LiteralPath $partial -Destination $Destination
    if ($drive.AvailableFreeSpace -lt $minimumFree) {
        throw "30 GiB reserve crossed after download"
    }
}

function Expand-VerifiedRuntime([string]$Archive, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        $server = Get-ChildItem -LiteralPath $Destination -Filter "llama-server.exe" -File -Recurse
        if ($server.Count -ne 1) {
            throw "Existing runtime is not verifiable: $Destination"
        }
        return
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $staging = "$Destination.staging"
    if (Test-Path -LiteralPath $staging) {
        throw "Stale runtime staging exists: $staging"
    }
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
        try {
            foreach ($entry in $zip.Entries) {
                $relative = $entry.FullName.Replace('/', [IO.Path]::DirectorySeparatorChar)
                if ([IO.Path]::IsPathRooted($relative) -or $relative.Split([IO.Path]::DirectorySeparatorChar) -contains '..') {
                    throw "Unsafe path in runtime archive: $relative"
                }
                $target = [IO.Path]::GetFullPath((Join-Path $staging $relative))
                if (-not $target.StartsWith(([IO.Path]::GetFullPath($staging) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Runtime archive escaped staging"
                }
            }
        } finally {
            $zip.Dispose()
        }
        [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $staging)
        $server = Get-ChildItem -LiteralPath $staging -Filter "llama-server.exe" -File -Recurse
        if ($server.Count -ne 1) {
            throw "Runtime must contain exactly one llama-server.exe"
        }
        Move-Item -LiteralPath $staging -Destination $Destination
    } catch {
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force
        }
        throw
    }
}

$runtimeAssets = @(
    [pscustomobject]@{ id = "cpu"; value = $manifest.runtime.profiles.cpu },
    [pscustomobject]@{ id = "vulkan"; value = $manifest.runtime.profiles.vulkan }
)
$modelAssets = @(
    [pscustomobject]@{ id = "q4_k_m"; value = $manifest.model.candidates.q4_k_m },
    [pscustomobject]@{ id = "q5_k_m"; value = $manifest.model.candidates.q5_k_m }
)

foreach ($entry in $runtimeAssets) {
    $archive = Join-Path $downloads ([string]$entry.value.asset)
    Receive-VerifiedAsset $entry.value $archive
    Expand-VerifiedRuntime $archive (Join-Path $runtimes $entry.id)
}
foreach ($entry in $modelAssets) {
    Receive-VerifiedAsset $entry.value (Join-Path $models ([string]$entry.value.file))
}

$licenseDownloads = @(
    [pscustomobject]@{ url = $manifest.license_sources.llama_cpp; path = (Join-Path $licenses "llama.cpp-MIT.txt") },
    [pscustomobject]@{ url = $manifest.license_sources.qwen3_8b; path = (Join-Path $licenses "Qwen3-8B-Apache-2.0.txt") }
)
foreach ($license in $licenseDownloads) {
    if (-not (Test-Path -LiteralPath $license.path)) {
        Invoke-WebRequest -UseBasicParsing -Uri $license.url -OutFile $license.path
    }
}

$inventory = Get-ChildItem -LiteralPath $cache -Recurse -File |
    Where-Object { $_.Name -notin @("INSTALLATION.json", "SBOM.spdx.json") } |
    Sort-Object FullName |
    ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($cache.Length + 1).Replace('\', '/')
            bytes = $_.Length
            sha256 = Get-LowerSha256 $_.FullName
        }
    }

$receipt = [ordered]@{
    schema = "casulo.family.day2-installation/1.0"
    installed_at_utc = [DateTime]::UtcNow.ToString("o")
    cache_root = $cache
    manifest_sha256 = Get-LowerSha256 $ManifestPath
    llama_cpp = [ordered]@{
        stable_release = $manifest.runtime.stable_release
        build_tag = $manifest.runtime.build_tag
        commit = $manifest.runtime.commit
        license = $manifest.runtime.license
    }
    model = [ordered]@{
        repository = $manifest.model.repository
        revision = $manifest.model.revision
        license = $manifest.model.license
    }
    minimum_free_bytes = $minimumFree
    free_bytes_after = $drive.AvailableFreeSpace
    files = @($inventory)
    rollback = "Stop Casulo processes, then remove only this cache_root after verifying no active process uses it."
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -LiteralPath (Join-Path $cache "INSTALLATION.json")

$packages = @(
    [ordered]@{
        SPDXID = "SPDXRef-llama-cpp-b10964"
        name = "llama.cpp"
        versionInfo = $manifest.runtime.build_tag
        downloadLocation = "https://github.com/ggml-org/llama.cpp/releases/tag/b10964"
        licenseConcluded = "MIT"
    },
    [ordered]@{
        SPDXID = "SPDXRef-Qwen3-8B-GGUF"
        name = "Qwen3-8B-GGUF"
        versionInfo = $manifest.model.revision
        downloadLocation = "https://huggingface.co/Qwen/Qwen3-8B-GGUF"
        licenseConcluded = "Apache-2.0"
    }
)
$sbom = [ordered]@{
    spdxVersion = "SPDX-2.3"
    dataLicense = "CC0-1.0"
    SPDXID = "SPDXRef-DOCUMENT"
    name = "Casulo-Family-RP01-Day2"
    documentNamespace = "https://casulo.local/spdx/family-rp01/day2/$([Guid]::NewGuid())"
    creationInfo = [ordered]@{
        created = [DateTime]::UtcNow.ToString("o")
        creators = @("Tool: Casulo-Day2-Bootstrap/1.0")
    }
    packages = $packages
}
$sbom | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -LiteralPath (Join-Path $cache "SBOM.spdx.json")

[ordered]@{
    status = "DAY2_ASSETS_VERIFIED"
    cache_root = $cache
    files = @($inventory).Count
    free_bytes_after = $drive.AvailableFreeSpace
    minimum_free_bytes = $minimumFree
} | ConvertTo-Json -Depth 4
