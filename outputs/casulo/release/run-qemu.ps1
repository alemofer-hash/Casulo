param(
    [int]$Repeat = 1,
    [switch]$VirtualUsb
)

$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Image = Join-Path $PSScriptRoot 'casulo-native-x86_64.img'
$Runner = if ($VirtualUsb) { 'os\tools\run_virtual_usb.py' } else { 'os\tools\run_qemu.py' }
python (Join-Path $Repository $Runner) --image $Image --repeat $Repeat
exit $LASTEXITCODE
