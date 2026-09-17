[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Execute,
    [switch]$IncludeDownloadsProjects,
    [switch]$IncludeVirtualBoxVMs,
    [string[]]$ProtectedRoots,
    [string]$ReportPath
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$userRoot = [System.IO.Path]::GetFullPath($env:USERPROFILE)
$localData = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA)
$downloadsRoot = Join-Path $userRoot 'Downloads'

$protectedRoots = if ($ProtectedRoots.Count -gt 0) {
    $ProtectedRoots
}
else {
    @($repositoryRoot, (Join-Path $downloadsRoot 'Jaderson'))
}

$cacheRoots = @(
    (Join-Path $localData 'pip\Cache'),
    (Join-Path $localData 'npm-cache'),
    (Join-Path $userRoot '.cache')
)

$singleFiles = @(
    (Join-Path $downloadsRoot 'archlinux-2026.07.01-x86_64.iso'),
    (Join-Path $downloadsRoot 'CASULO_PRODUCT_EXECUTION_PACKAGE_2026-08-11 (1).zip'),
    (Join-Path $downloadsRoot 'CASULO_PRODUCT_EXECUTION_PACKAGE_2026-08-11 (2).zip')
)

$downloadProjects = @(
    (Join-Path $downloadsRoot 'AeroDreamer_FullStack_Desktop'),
    (Join-Path $downloadsRoot 'greaterTHANtony'),
    (Join-Path $downloadsRoot 'ITA_HBits_Exam_Engine'),
    (Join-Path $downloadsRoot 'telencefalus_desktop_v0_4_0')
)

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$LiteralPath)

    $full = [System.IO.Path]::GetFullPath($LiteralPath)
    return $full.TrimEnd([System.IO.Path]::DirectorySeparatorChar)
}

function Test-PathCollision {
    param(
        [Parameter(Mandatory)][string]$Candidate,
        [Parameter(Mandatory)][string[]]$Protected
    )

    $candidatePath = Get-NormalizedPath $Candidate
    foreach ($root in $Protected) {
        $protectedPath = Get-NormalizedPath $root
        $candidatePrefix = $candidatePath + [System.IO.Path]::DirectorySeparatorChar
        $protectedPrefix = $protectedPath + [System.IO.Path]::DirectorySeparatorChar

        if ($candidatePath.Equals($protectedPath, [System.StringComparison]::OrdinalIgnoreCase) -or
            $candidatePath.StartsWith($protectedPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
            $protectedPath.StartsWith($candidatePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-TreeBytes {
    param([Parameter(Mandatory)][string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return [int64]0
    }

    $item = Get-Item -LiteralPath $LiteralPath -Force
    if (-not $item.PSIsContainer) {
        return [int64]$item.Length
    }

    $sum = [int64]0
    Get-ChildItem -LiteralPath $item.FullName -File -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object { $sum += [int64]$_.Length }
    return $sum
}

function New-Candidate {
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [Parameter(Mandatory)][string]$Kind,
        [Parameter(Mandatory)][bool]$ContentsOnly,
        [int]$MinimumAgeHours = 0
    )

    $normalized = Get-NormalizedPath $LiteralPath
    if (Test-PathCollision -Candidate $normalized -Protected $protectedRoots) {
        throw "Refusing protected-path collision: $normalized"
    }

    [pscustomobject]@{
        path = $normalized
        kind = $Kind
        contents_only = $ContentsOnly
        minimum_age_hours = $MinimumAgeHours
        exists = Test-Path -LiteralPath $normalized
        bytes_before = Get-TreeBytes $normalized
    }
}

$resolvedProtected = foreach ($root in $protectedRoots) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "Protected root is missing: $root"
    }
    (Get-Item -LiteralPath $root -Force).FullName
}

$candidates = @()
foreach ($path in $cacheRoots) {
    $candidates += New-Candidate -LiteralPath $path -Kind 'regenerable_cache' -ContentsOnly $true
}
$candidates += New-Candidate -LiteralPath (Join-Path $localData 'Temp') -Kind 'user_temp' -ContentsOnly $true -MinimumAgeHours 24
foreach ($path in $singleFiles) {
    $candidates += New-Candidate -LiteralPath $path -Kind 'redundant_or_regenerable_file' -ContentsOnly $false
}
if ($IncludeDownloadsProjects) {
    foreach ($path in $downloadProjects) {
        $candidates += New-Candidate -LiteralPath $path -Kind 'authorized_legacy_download_project' -ContentsOnly $false
    }
}
if ($IncludeVirtualBoxVMs) {
    $candidates += New-Candidate -LiteralPath (Join-Path $userRoot 'VirtualBox VMs') -Kind 'authorized_virtualbox_vm_storage' -ContentsOnly $false
}

$freeBefore = (Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
$actions = @()

foreach ($candidate in $candidates) {
    $action = 'not_present'
    $errorMessage = $null

    if ($candidate.exists) {
        $action = if ($Execute) { 'delete_requested' } else { 'dry_run' }
        if ($Execute) {
            if ($candidate.contents_only) {
                $failures = @()
                $deletedChildren = 0
                $children = Get-ChildItem -LiteralPath $candidate.path -Force -ErrorAction SilentlyContinue
                foreach ($child in $children) {
                    try {
                        if ($candidate.minimum_age_hours -gt 0 -and
                            $child.LastWriteTimeUtc -gt (Get-Date).ToUniversalTime().AddHours(-$candidate.minimum_age_hours)) {
                            continue
                        }
                        $childPath = Get-NormalizedPath $child.FullName
                        if (Test-PathCollision -Candidate $childPath -Protected $resolvedProtected) {
                            throw "Refusing protected child collision: $childPath"
                        }
                        if ($PSCmdlet.ShouldProcess($childPath, 'Remove regenerable item')) {
                            Remove-Item -LiteralPath $childPath -Recurse -Force -ErrorAction Stop
                            $deletedChildren += 1
                        }
                    }
                    catch {
                        $failures += $_.Exception.Message
                    }
                }
                $action = if ($failures.Count -gt 0) { 'partial_or_locked' } else { 'deleted' }
                if ($failures.Count -gt 0) {
                    $errorMessage = ($failures | Select-Object -First 10) -join ' | '
                }
            }
            else {
                try {
                    if ($PSCmdlet.ShouldProcess($candidate.path, 'Remove approved item')) {
                    Remove-Item -LiteralPath $candidate.path -Recurse -Force -ErrorAction Stop
                    }
                    $action = 'deleted'
                }
                catch {
                    $action = 'partial_or_locked'
                    $errorMessage = $_.Exception.Message
                }
            }
        }
    }

    $actions += [pscustomobject]@{
        path = $candidate.path
        kind = $candidate.kind
        contents_only = $candidate.contents_only
        minimum_age_hours = $candidate.minimum_age_hours
        bytes_before = $candidate.bytes_before
        action = $action
        error = $errorMessage
    }
}

$freeAfter = (Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
$report = [ordered]@{
    schema = 'casulo-host-space-report/1.0'
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    mode = if ($Execute) { 'execute' } else { 'dry-run' }
    protected_roots = $resolvedProtected
    include_download_projects = [bool]$IncludeDownloadsProjects
    include_virtualbox_vms = [bool]$IncludeVirtualBoxVMs
    free_bytes_before = [int64]$freeBefore
    free_bytes_after = [int64]$freeAfter
    reclaimed_bytes_observed = [int64]($freeAfter - $freeBefore)
    actions = $actions
}

$json = $report | ConvertTo-Json -Depth 6
if ($ReportPath) {
    $parent = Split-Path -Parent $ReportPath
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($ReportPath, $json, [System.Text.UTF8Encoding]::new($false))
}
$json
