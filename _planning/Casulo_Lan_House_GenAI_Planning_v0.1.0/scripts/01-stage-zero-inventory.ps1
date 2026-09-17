[CmdletBinding()]
param(
    [string]$Root = 'C:\Users\guimo\Downloads\ex',
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    throw "Root does not exist: $Root"
}

$output = Join-Path $Root '_stage0'
if (-not $Apply) {
    Write-Host 'DRY RUN: this would create:' -ForegroundColor Yellow
    Write-Host "  $output\inventory.csv"
    Write-Host "  $output\sha256.csv"
    Write-Host "  $output\summary.json"
    Write-Host 'Run again with -Apply only after reviewing 00-preflight-readonly.ps1 output.'
    exit 0
}

New-Item -ItemType Directory -Path $output -Force | Out-Null
$rootPrefix = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'

$files = @(Get-ChildItem -LiteralPath $Root -Recurse -Force -File |
    Where-Object { $_.FullName -notlike "$output\*" -and $_.FullName -notmatch '[\\/]\.git[\\/]' })

$inventory = $files | ForEach-Object {
    [pscustomobject]@{
        RelativePath = $_.FullName.Substring($rootPrefix.Length)
        Bytes = $_.Length
        LastWriteTimeUtc = $_.LastWriteTimeUtc.ToString('o')
        Extension = $_.Extension
    }
}
$inventory | Export-Csv -LiteralPath (Join-Path $output 'inventory.csv') -NoTypeInformation -Encoding utf8

$hashes = $files | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    [pscustomobject]@{
        RelativePath = $_.FullName.Substring($rootPrefix.Length)
        SHA256 = $hash.Hash.ToLowerInvariant()
        Bytes = $_.Length
    }
}
$hashes | Export-Csv -LiteralPath (Join-Path $output 'sha256.csv') -NoTypeInformation -Encoding utf8

$summary = [ordered]@{
    schema_version = 1
    generated_utc = [DateTime]::UtcNow.ToString('o')
    root = $Root
    file_count = $files.Count
    total_bytes = [long](($files | Measure-Object Length -Sum).Sum)
    files_over_100mb = @($files | Where-Object Length -ge 100MB).Count
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'summary.json') -Encoding utf8

Write-Host "Stage Zero inventory written to $output" -ForegroundColor Green
Write-Host 'No Git repository or commit was created. Review the outputs before staging files.'
