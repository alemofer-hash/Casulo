[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputCsv,

    [Parameter(Mandatory = $true)]
    [string]$OutputJson
)

$ErrorActionPreference = 'Stop'
$rows = @(Import-Csv -LiteralPath $InputCsv)
if ($rows.Count -lt 2) {
    throw 'typeperf evidence has fewer than two rows'
}
$columns = @($rows[0].PSObject.Properties.Name)
if ($columns.Count -ne 6) {
    throw "unexpected typeperf column count: $($columns.Count)"
}
$numberStyle = [System.Globalization.NumberStyles]::Float
$invariant = [System.Globalization.CultureInfo]::InvariantCulture
function Convert-InvariantDouble([string]$Value) {
    $number = 0.0
    if ([double]::TryParse($Value.Trim(), $numberStyle, $invariant, [ref]$number)) {
        return $number
    }
    return $null
}
$parsed = @(
    $rows | ForEach-Object {
        $properties = @($_.PSObject.Properties)
        $values = @(
            Convert-InvariantDouble ([string]$properties[1].Value)
            Convert-InvariantDouble ([string]$properties[2].Value)
            Convert-InvariantDouble ([string]$properties[3].Value)
            Convert-InvariantDouble ([string]$properties[4].Value)
            Convert-InvariantDouble ([string]$properties[5].Value)
        )
        if ($values -contains $null) {
            return
        }
        [pscustomobject]@{
            timestamp = [string]$properties[0].Value
            limit_flags = $values[0]
            limit_percent = $values[1]
            actual_mhz = $values[2]
            nominal_mhz = $values[3]
            performance_percent = $values[4]
        }
    }
)
$valid = @($parsed | Where-Object { $_.limit_percent -gt 0 -and $_.nominal_mhz -gt 0 })
if ($valid.Count -lt 2) {
    throw 'typeperf evidence has fewer than two initialized rows'
}
$nonzeroFlags = @($valid | Where-Object { $_.limit_flags -ne 0 }).Count
$belowHundredLimit = @($valid | Where-Object { $_.limit_percent -lt 100 }).Count
$document = [ordered]@{
    schema = 'casulo.family.day2-processor-counters/1.0'
    source = 'Windows Processor Information performance counters via typeperf'
    samples_total = $parsed.Count
    samples_initialized = $valid.Count
    first_timestamp = $valid[0].timestamp
    last_timestamp = $valid[-1].timestamp
    performance_limit_flags_nonzero_samples = $nonzeroFlags
    performance_limit_below_100_samples = $belowHundredLimit
    max_performance_limit_flags = ($valid.limit_flags | Measure-Object -Maximum).Maximum
    min_performance_limit_percent = ($valid.limit_percent | Measure-Object -Minimum).Minimum
    min_actual_mhz = ($valid.actual_mhz | Measure-Object -Minimum).Minimum
    max_actual_mhz = ($valid.actual_mhz | Measure-Object -Maximum).Maximum
    average_actual_mhz = [math]::Round(($valid.actual_mhz | Measure-Object -Average).Average, 3)
    temperature_celsius = $null
    temperature_status = 'UNAVAILABLE'
    no_persistent_processor_limit_observed = ($nonzeroFlags -eq 0 -and $belowHundredLimit -eq 0)
    limitation = 'Performance counters are a throttling proxy and do not measure absolute temperature.'
}
$parent = Split-Path -Parent $OutputJson
if ($parent) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$document | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
$document | ConvertTo-Json -Depth 5 -Compress
