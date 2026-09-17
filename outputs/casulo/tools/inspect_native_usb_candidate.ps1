[CmdletBinding()]
param(
  [int]$CandidateDiskNumber = -1,
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Get-LocalFingerprint([string]$Value) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

$observed = @(Get-Disk | Sort-Object Number | ForEach-Object {
  $eligible = $_.BusType -eq "USB" -and -not $_.IsBoot -and -not $_.IsSystem -and $_.Size -ge 8GB
  [ordered]@{
    number = [int]$_.Number
    friendly_name = [string]$_.FriendlyName
    bus_type = [string]$_.BusType
    size_bytes = [uint64]$_.Size
    partition_style = [string]$_.PartitionStyle
    operational_status = @($_.OperationalStatus | ForEach-Object { [string]$_ })
    is_boot = [bool]$_.IsBoot
    is_system = [bool]$_.IsSystem
    read_only = [bool]$_.IsReadOnly
    local_fingerprint_sha256 = Get-LocalFingerprint ([string]$_.UniqueId)
    eligible_candidate = [bool]$eligible
  }
})

$candidates = @($observed | Where-Object { $_.eligible_candidate })
$selected = $null
if ($CandidateDiskNumber -ge 0) {
  $matches = @($candidates | Where-Object { $_.number -eq $CandidateDiskNumber })
  if ($matches.Count -eq 1) { $selected = $matches[0] }
}
$state = if ($CandidateDiskNumber -ge 0 -and $null -eq $selected) {
  "REFUSED_NOT_ELIGIBLE"
} elseif ($null -ne $selected) {
  "CANDIDATE_IDENTIFIED_READ_ONLY"
} elseif ($candidates.Count -eq 0) {
  "NO_ELIGIBLE_USB_PRESENT"
} elseif ($candidates.Count -eq 1) {
  "ONE_CANDIDATE_AWAITS_EXPLICIT_SELECTION"
} else {
  "AMBIGUOUS_MULTIPLE_CANDIDATES"
}

$result = [ordered]@{
  schema = "casulo-native-usb-candidate-preflight/0.1"
  state = $state
  disks = $observed
  eligible_candidates = $candidates
  selected_candidate = $selected
  image_written = $false
  physical_device_written = $false
  destructive_confirmation_received = $false
  next_gate = "separate explicit destructive authorization after native neural conversation exists"
}
$json = $result | ConvertTo-Json -Depth 8
if ($OutputPath) {
  $resolved = [IO.Path]::GetFullPath($OutputPath)
  if (-not $resolved.StartsWith($repo + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputPath precisa permanecer no repositorio"
  }
  $parent = Split-Path -Parent $resolved
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  [IO.File]::WriteAllText($resolved, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}
$json
