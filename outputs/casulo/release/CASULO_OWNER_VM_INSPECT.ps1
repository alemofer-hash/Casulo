$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = "$repoRoot\src;$repoRoot\private\casulo-owner\src"
$cacheRoot = Join-Path $env:LOCALAPPDATA 'Casulo\cache\generative'
$vmRoot = Join-Path $repoRoot 'outputs\casulo\generative-vm\guilherme-live'
$feedbackRoot = Join-Path $repoRoot 'outputs\casulo\generative-vm\guilherme-feedback'

& python (Join-Path $repoRoot 'tools\casulo_owner_vm_inspect.py') `
  --source-image (Join-Path $repoRoot 'release\casulo-native-generative-interactive.img') `
  --candidate (Join-Path $repoRoot 'release\generative-candidates\qwen3-4b-q4km-llamacpp-b10362.json') `
  --cache $cacheRoot `
  --vm-root $vmRoot `
  --feedback-root $feedbackRoot `
  --repo $repoRoot `
  --threads 4

exit $LASTEXITCODE
