$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = "$repoRoot\src;$repoRoot\private\casulo-owner\src"
$cacheRoot = Join-Path $env:LOCALAPPDATA 'Casulo\cache\generative'
$vmRoot = Join-Path $repoRoot 'outputs\casulo\semantic-multiverse-vm\guilherme-reinspection-2026-08-13'
$feedbackRoot = Join-Path $repoRoot 'outputs\casulo\semantic-multiverse-vm\guilherme-reinspection-feedback-2026-08-13'

& python (Join-Path $repoRoot 'tools\casulo_semantic_multiverse.py') doctor --repo $repoRoot
if ($LASTEXITCODE -ne 0) {
  Write-Host 'Reinspecao bloqueada: o doctor read-only nao aprovou o selo atual.'
  exit $LASTEXITCODE
}

Write-Host 'Casulo Semantic Multiverse — sessao limpa de reinspecao humana.'
Write-Host 'Estado: READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION'

& python (Join-Path $repoRoot 'tools\casulo_semantic_multiverse_vm_inspect.py') `
  --source-image (Join-Path $repoRoot 'release\casulo-native-generative-interactive.img') `
  --candidate (Join-Path $repoRoot 'release\generative-candidates\qwen3-4b-q4km-llamacpp-b10362.json') `
  --cache $cacheRoot `
  --vm-root $vmRoot `
  --feedback-root $feedbackRoot `
  --repo $repoRoot `
  --threads 4

exit $LASTEXITCODE
