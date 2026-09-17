[CmdletBinding()]
param(
    [int]$RunnerPid = 0,
    [string]$Campaign = "C:\CasuloLab\campaigns\2026-09-09-video8k-proof-v1-live-attempt3"
)

$ErrorActionPreference = "Stop"
$expectedBytes = [int64]18381885157
$arms = Join-Path $Campaign "arms"
$reportFile = Join-Path $arms "report.json"
$stderrLog = Join-Path $Campaign "resume.stderr.log"

function Find-RunnerPid {
    $matches = @(
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine -match 'casulo\.compression\.cli resume-baseline' -and
                $_.CommandLine -match [regex]::Escape($Campaign)
            }
    )
    if ($matches.Count -eq 1) { return [int]$matches[0].ProcessId }
    if ($matches.Count -gt 1) { throw "Mais de um runner corresponde a campanha." }
    return 0
}

function Get-LargestFileBytes([string]$Directory) {
    if (-not (Test-Path -LiteralPath $Directory)) { return [int64]0 }
    $files = @(Get-ChildItem -LiteralPath $Directory -File -Recurse -Force -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) { return [int64]0 }
    return [int64](($files | Measure-Object -Property Length -Maximum).Maximum)
}

function Show-FinalReport {
    param([string]$Path)
    $report = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    Write-Host "CASULO | RESULTADO FINAL 8K" -ForegroundColor Cyan
    if (@($report.results | Where-Object { -not $_.bit_exact }).Count -gt 0) {
        Write-Host "FAIL: ao menos um round-trip divergiu." -ForegroundColor Red
        return
    }
    Write-Host "PASS_BIT_EXACT: tres reconstrucoes identicas a fonte." -ForegroundColor Green
    Write-Host ("JULGAMENTO: {0}" -f $report.comparison.classification) -ForegroundColor Yellow
    foreach ($result in $report.results) {
        Write-Host ("{0,-24} {1,16:N0} bytes | reducao {2,9:N4}%" -f $result.name, $result.archive_bytes, $result.reduction_percent)
    }
    Write-Host ("Razao Casulo/melhor baseline: {0:N9}" -f $report.comparison.candidate_to_best_baseline_ratio)
    Write-Host "Relatorio: $Path" -ForegroundColor Cyan
}

if ($RunnerPid -eq 0) { $RunnerPid = Find-RunnerPid }
if ($RunnerPid -eq 0 -and (Test-Path -LiteralPath $reportFile)) {
    Show-FinalReport -Path $reportFile
    exit 0
}
if ($RunnerPid -eq 0) {
    Write-Host "Nenhum runner vivo e report.json ainda ausente." -ForegroundColor Red
    if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Tail 40 }
    exit 2
}

$attached = Get-Date
$lastCpu = 0.0
$lastSample = Get-Date
while ($true) {
    $runner = Get-Process -Id $RunnerPid -ErrorAction SilentlyContinue
    if ($null -eq $runner) { break }
    $now = Get-Date
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$RunnerPid")
    $childCommands = @($children.CommandLine)
    $casuloReceipt = Join-Path $arms "casulo\resume-result.json"
    $zstdReceipt = Join-Path $arms "zstd\resume-result.json"
    $sevenReceipt = Join-Path $arms "7zip\resume-result.json"
    $sevenRestored = Join-Path $arms "7zip\restored\000_10sec_8K.mp4"
    if (Test-Path -LiteralPath $reportFile) { $stage = "COMPLETE" }
    elseif (-not (Test-Path -LiteralPath $casuloReceipt)) { $stage = "REVALIDANDO CASULO + SHA-256" }
    elseif (-not (Test-Path -LiteralPath $zstdReceipt)) { $stage = "REVALIDANDO ZSTD + SHA-256" }
    elseif (Test-Path -LiteralPath $sevenRestored) { $stage = "7ZIP ROUND-TRIP + SHA-256" }
    elseif ($childCommands -match '\s(?:e|x)\s') { $stage = "7ZIP ROUND-TRIP" }
    elseif (-not (Test-Path -LiteralPath $sevenReceipt)) { $stage = "7ZIP PACK REINICIADO" }
    else { $stage = "SELANDO RELATORIO" }

    $allIds = @($RunnerPid) + @($children | ForEach-Object { [int]$_.ProcessId })
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
    $sevenBytes = Get-LargestFileBytes (Join-Path $arms "7zip")

    Clear-Host
    Write-Host "CASULO | TELEMETRIA ELEVADA | PROVA REAL 8K" -ForegroundColor Cyan
    Write-Host ("ADMIN : {0} | runner PID: {1}" -f ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator), $RunnerPid) -ForegroundColor White
    Write-Host "Fonte: 8192x4320 | 600 frames | 18.381.885.157 bytes" -ForegroundColor White
    Write-Host ""
    Write-Host ("FASE  : {0}" -f $stage) -ForegroundColor Yellow
    Write-Host ("ANEXO : {0:hh\:mm\:ss}" -f ($now - $attached))
    Write-Host ("CPU   : {0,6:N1}% total | RAM campanha: {1,8:N1} MiB" -f $cpuPercent, ($rss / 1MB))
    Write-Host ("DISCO : {0,8:N1} GiB livres | reserva: 30 GiB" -f $freeGiB)
    if ($sevenBytes -gt 0) {
        Write-Host ("7ZIP : {0:N0} bytes | razao provisoria: {1:N6}" -f $sevenBytes, ($sevenBytes / $expectedBytes)) -ForegroundColor Magenta
    }
    Write-Host ""
    Write-Host "Este terminal observa; nao inicia nem duplica o workload." -ForegroundColor DarkGray
    Write-Host "Nada e sucesso ate o report.json e os tres SHA-256." -ForegroundColor DarkYellow
    Start-Sleep -Seconds 2
}

Clear-Host
if (Test-Path -LiteralPath $reportFile) {
    Show-FinalReport -Path $reportFile
    exit 0
}
Write-Host "O runner terminou sem report.json." -ForegroundColor Red
if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Tail 40 }
exit 3
