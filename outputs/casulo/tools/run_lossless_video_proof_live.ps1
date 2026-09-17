[CmdletBinding()]
param(
    [string]$Source = "C:\CasuloLab\incoming\000_10sec_8K.mp4",
    [string]$Campaign = "C:\CasuloLab\campaigns\2026-09-09-video8k-proof-v1-live-attempt3"
)

$ErrorActionPreference = "Stop"
$expectedBytes = [int64]18381885157
$expectedSha256 = "68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24"
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$arms = Join-Path $Campaign "arms"
$protocol = Join-Path $Campaign "frozen_protocol.json"
$stdoutLog = Join-Path $Campaign "runner.stdout.log"
$stderrLog = Join-Path $Campaign "runner.stderr.log"

$sourceItem = Get-Item -LiteralPath $Source
if ($sourceItem.Length -ne $expectedBytes) {
    throw "Fonte recusada: tamanho divergente."
}
if (-not (Test-Path -LiteralPath $protocol -PathType Leaf)) {
    throw "Protocolo congelado ausente: $protocol"
}
if (Test-Path -LiteralPath $arms) {
    throw "Campanha append-only já iniciada: $arms"
}

$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @(
    "-m", "casulo.compression.cli", "baseline",
    $Source, $arms, "--profile", "balanced", "--chunk-mib", "4",
    "--expected-bytes", "$expectedBytes", "--expected-sha256", $expectedSha256
)
$started = Get-Date
$runner = Start-Process -FilePath $python -ArgumentList $arguments `
    -WorkingDirectory $repo -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog -NoNewWindow -PassThru
$lastCpu = 0.0
$lastSample = Get-Date

function Get-LargestFileBytes([string]$Directory) {
    if (-not (Test-Path -LiteralPath $Directory)) { return [int64]0 }
    $files = @(Get-ChildItem -LiteralPath $Directory -File -Recurse -Force -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) { return [int64]0 }
    return [int64](($files | Measure-Object -Property Length -Maximum).Maximum)
}

try {
    while (-not $runner.HasExited) {
        Start-Sleep -Seconds 1
        $runner.Refresh()
        $now = Get-Date
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($runner.Id)"
        $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $runner.Id })
        $childNames = @($children.Name)
        $readBytes = if ($null -ne $cim) { [int64]$cim.ReadTransferCount } else { 0 }

        $casuloDir = Join-Path $arms "casulo"
        $zstdDir = Join-Path $arms "zstd"
        $sevenDir = Join-Path $arms "7zip"
        $casuloArchive = Join-Path $casuloDir "000_10sec_8K.mp4.casulo"
        $reportPath = Join-Path $arms "report.json"
        if (Test-Path -LiteralPath $reportPath) { $stage = "COMPLETE" }
        elseif (($childNames -contains "7z.exe") -or (Test-Path -LiteralPath $sevenDir)) { $stage = "7ZIP" }
        elseif (($childNames -contains "zstd.exe") -or (Test-Path -LiteralPath $zstdDir)) { $stage = "ZSTD" }
        elseif (Test-Path -LiteralPath $casuloArchive) { $stage = "CASULO ROUND-TRIP" }
        elseif (Test-Path -LiteralPath $casuloDir) { $stage = "CASULO PACK" }
        else { $stage = "SHA-256 DA FONTE" }

        $progress = $null
        if ($stage -eq "SHA-256 DA FONTE") {
            $progress = [math]::Min(100.0, 100.0 * $readBytes / $expectedBytes)
        }
        elseif ($stage -eq "CASULO PACK") {
            $progress = [math]::Min(100.0, [math]::Max(0.0, 100.0 * ($readBytes - $expectedBytes) / $expectedBytes))
        }

        $allIds = @($runner.Id) + @(
            $children |
                Where-Object { $null -ne $_.ProcessId } |
                ForEach-Object { [int]$_.ProcessId }
        )
        $cpuTotal = 0.0
        $rss = [int64]0
        foreach ($processId in $allIds) {
            $live = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($null -ne $live) {
                $cpuTotal += [double]$live.CPU
                $rss += [int64]$live.WorkingSet64
            }
        }
        $sampleSeconds = [math]::Max(0.001, ($now - $lastSample).TotalSeconds)
        $cpuPercent = 100.0 * [math]::Max(0.0, $cpuTotal - $lastCpu) / $sampleSeconds / [Environment]::ProcessorCount
        $lastCpu = $cpuTotal
        $lastSample = $now
        $currentDir = if ($stage -like "CASULO*") { $casuloDir } elseif ($stage -eq "ZSTD") { $zstdDir } else { $sevenDir }
        $outputBytes = Get-LargestFileBytes $currentDir
        $freeGiB = (Get-Volume -DriveLetter C).SizeRemaining / 1GB

        Clear-Host
        Write-Host "CASULO | PROVA REAL 8K | SEM PERDA" -ForegroundColor Cyan
        Write-Host "Fonte: 8192x4320 | 600 frames | 18.381.885.157 bytes" -ForegroundColor White
        Write-Host "SHA-256 esperado: $expectedSha256" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host ("FASE  : {0}" -f $stage) -ForegroundColor Yellow
        if ($null -ne $progress) {
            $filled = [math]::Min(40, [math]::Floor($progress / 2.5))
            $bar = ("#" * $filled).PadRight(40, ".")
            Write-Host ("LEITURA: [{0}] {1,6:N1}%" -f $bar, $progress) -ForegroundColor Green
        } else {
            Write-Host "LEITURA: verificação integral; porcentagem não inferida" -ForegroundColor DarkYellow
        }
        Write-Host ("TEMPO : {0:hh\:mm\:ss}" -f ($now - $started))
        Write-Host ("CPU   : {0,6:N1}% total | RAM campanha: {1,8:N1} MiB" -f $cpuPercent, ($rss / 1MB))
        Write-Host ("DISCO : {0,8:N1} GiB livres | reserva: 30 GiB" -f $freeGiB)
        if ($outputBytes -gt 0) {
            Write-Host ("OUTPUT: {0:N0} bytes | razão provisória: {1:N6}" -f $outputBytes, ($outputBytes / $expectedBytes)) -ForegroundColor Magenta
        } else {
            Write-Host "OUTPUT: ainda não materializado" -ForegroundColor DarkGray
        }
        Write-Host ""
        Write-Host "fonte real: PASS | compressão: RUNNING | round-trip: WAIT" -ForegroundColor Yellow
        Write-Host "Nada é sucesso até o SHA-256 restaurado coincidir." -ForegroundColor DarkYellow
    }
    $runner.WaitForExit()
}
finally {
    if (-not $runner.HasExited) {
        Stop-Process -Id $runner.Id -Force -ErrorAction SilentlyContinue
    }
}

Clear-Host
Write-Host "CASULO | RESULTADO DA PROVA REAL 8K" -ForegroundColor Cyan
if ($runner.ExitCode -ne 0) {
    Write-Host "FAIL: runner encerrou com código $($runner.ExitCode)." -ForegroundColor Red
    if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Tail 30 }
    exit $runner.ExitCode
}
$reportFile = Join-Path $arms "report.json"
if (-not (Test-Path -LiteralPath $reportFile -PathType Leaf)) {
    Write-Host "FAIL: report.json ausente." -ForegroundColor Red
    exit 3
}
$report = Get-Content -Raw -LiteralPath $reportFile | ConvertFrom-Json
$invalid = @($report.results | Where-Object { -not $_.bit_exact })
if ($invalid.Count -gt 0) {
    Write-Host "FAIL: round-trip divergente." -ForegroundColor Red
    exit 4
}
Write-Host "PASS_BIT_EXACT: os três braços reconstruíram a fonte." -ForegroundColor Green
Write-Host ("JULGAMENTO: {0}" -f $report.comparison.classification) -ForegroundColor Yellow
foreach ($result in $report.results) {
    Write-Host ("{0,-24} {1,16:N0} bytes | redução {2,9:N4}% | enc {3,9:N2}s | dec {4,9:N2}s" -f $result.name, $result.archive_bytes, $result.reduction_percent, $result.encode_seconds, $result.decode_seconds)
}
Write-Host ("Razão Casulo/melhor baseline: {0:N9}" -f $report.comparison.candidate_to_best_baseline_ratio)
Write-Host "Relatório: $reportFile" -ForegroundColor Cyan
Write-Host "Uma fonte real não autoriza alegação universal." -ForegroundColor DarkYellow
