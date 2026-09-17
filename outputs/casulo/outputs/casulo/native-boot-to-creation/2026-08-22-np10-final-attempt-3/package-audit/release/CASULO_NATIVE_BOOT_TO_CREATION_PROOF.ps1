$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $repoRoot "os\tools\launch_native_creation_visible.py"
$image = Join-Path $repoRoot "release\casulo-native-neural-port-np10-attempt-5.img"
$model = Join-Path $env:LOCALAPPDATA "Casulo\cache\generative\qwen3-4b-q4km-llamacpp-b10362\model\Qwen3-4B-Q4_K_M.gguf"

foreach ($dependency in @($launcher, $image, $model)) {
  if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) {
    throw "Dependencia ausente: $dependency"
  }
}

& python $launcher --image $image --model $model --accelerator whpx
exit $LASTEXITCODE
