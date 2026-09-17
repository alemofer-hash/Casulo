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
$stdoutLog = Join-Path $Campaign "resume.stdout.log"
$stderrLog = Join-Path $Campaign "resume.stderr.log"
$reportFile = Join-Path $arms "report.json"

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Fonte ausente: $Source"
}
if ((Get-Item -LiteralPath $Source).Length -ne $expectedBytes) {
    throw "Fonte recusada: tamanho divergente."
}
if (-not (Test-Path -LiteralPath $protocol -PathType Leaf)) {
    throw "Protocolo congelado ausente: $protocol"
}
if (-not (Test-Path -LiteralPath $arms -PathType Container)) {
    throw "Diretório interrompido ausente: $arms"
}
if (Test-Path -LiteralPath $reportFile -PathType Leaf) {
    Write-Host "A campanha já possui report.json; nenhuma execução foi iniciada." -ForegroundColor Yellow
    Write-Host $reportFile -ForegroundColor Cyan
    exit 0
}
if ((Test-Path -LiteralPath $stdoutLog) -or (Test-Path -LiteralPath $stderrLog)) {
    throw "Uma retomada já foi iniciada; logs append-only existentes."
}

$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @(
    "-m", "casulo.compression.cli", "resume-baseline",
    $Source, $arms,
    "--expected-bytes", "$expectedBytes",
    "--expected-sha256", $expectedSha256
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

function Format-Seconds($Value) {
    if ($null -eq $Value) { return "não medido na execução interrompida" }
    return ("{0:N2}s" -f [double]$Value)
}

while (-not $runner.HasExited) {
    Start-Sleep -Seconds 1
    $runner.Refresh()
    $now = Get-Date
    $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $runner.Id })
    $childCommands = @($children.CommandLine)
    $casuloReceipt = Join-Path $arms "casulo\resume-result.json"
    $zstdReceipt = Join-Path $arms "zstd\resume-result.json"
    $sevenReceipt = Join-Path $arms "7zip\resume-result.json"
    $sevenRestored = Join-Path $arms "7zip\restored\000_10sec_8K.mp4"
    if (Test-Path -LiteralPath $reportFile) { $stage = "COMPLETE" }
    elseif (-not (Test-Path -LiteralPath $casuloReceipt)) { $stage = "REVALIDANDO CASULO + SHA-256" }
    elseif (-not (Test-Path -LiteralPath $zstdReceipt)) { $stage = "REVALIDANDO ZSTD + SHA-256" }
    elseif (Test-Path -LiteralPath $sevenRestored) { $stage = "7ZIP ROUND-TRIP + SHA-256" }
    elseif ($childCommands -match '\s[e|x]\s') { $stage = "7ZIP ROUND-TRIP" }
    elseif (-not (Test-Path -LiteralPath $sevenReceipt)) { $stage = "7ZIP PACK REINICIADO" }
    else { $stage = "SELANDO RELATÓRIO" }

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
    $freeGiB = (Get-Volume -DriveLetter C).SizeRemaining / 1GB
    $outputBytes = Get-LargestFileBytes (Join-Path $arms "7zip")

    Clear-Host
    Write-Host "CASULO | RETOMADA REAL 8K | SEM PERDA" -ForegroundColor Cyan
    Write-Host "Fonte: 8192x4320 | 600 frames | 18.381.885.157 bytes" -ForegroundColor White
    Write-Host "SHA-256: $expectedSha256" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host ("FASE  : {0}" -f $stage) -ForegroundColor Yellow
    Write-Host ("TEMPO : {0:hh\:mm\:ss}" -f ($now - $started))
    Write-Host ("CPU   : {0,6:N1}% total | RAM campanha: {1,8:N1} MiB" -f $cpuPercent, ($rss / 1MB))
    Write-Host ("DISCO : {0,8:N1} GiB livres | reserva: 30 GiB" -f $freeGiB)
    if ($outputBytes -gt 0) {
        Write-Host ("7ZIP : {0:N0} bytes | razão provisória: {1:N6}" -f $outputBytes, ($outputBytes / $expectedBytes)) -ForegroundColor Magenta
    }
    Write-Host ""
    Write-Host "Casulo e zstd serão aceitos somente após novo round-trip exato." -ForegroundColor DarkYellow
    Write-Host "O fragmento inválido do 7-Zip será preservado em rejected/." -ForegroundColor DarkYellow
    Write-Host "Nada é sucesso até os três SHA-256 restaurados coincidirem." -ForegroundColor Yellow
}
$runner.WaitForExit()

Clear-Host
Write-Host "CASULO | RESULTADO DA RETOMADA 8K" -ForegroundColor Cyan
if ($runner.ExitCode -ne 0) {
    Write-Host "FAIL: runner encerrou com código $($runner.ExitCode)." -ForegroundColor Red
    if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Tail 40 }
    Write-Host "A janela permanecerá aberta para inspeção." -ForegroundColor Yellow
    exit $runner.ExitCode
}
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
Write-Host "PASS_BIT_EXACT: os três braços reconstruíram a fonte byte a byte." -ForegroundColor Green
Write-Host ("JULGAMENTO: {0}" -f $report.comparison.classification) -ForegroundColor Yellow
foreach ($result in $report.results) {
    Write-Host ("{0,-24} {1,16:N0} bytes | redução {2,9:N4}%" -f $result.name, $result.archive_bytes, $result.reduction_percent)
    Write-Host ("  encode: {0} | decode: {1}" -f (Format-Seconds $result.encode_seconds), (Format-Seconds $result.decode_seconds)) -ForegroundColor DarkGray
}
Write-Host ("Razão Casulo/melhor baseline: {0:N9}" -f $report.comparison.candidate_to_best_baseline_ratio)
Write-Host "Relatório: $reportFile" -ForegroundColor Cyan
Write-Host "Limite: uma fonte real; nenhuma alegação universal." -ForegroundColor DarkYellow
