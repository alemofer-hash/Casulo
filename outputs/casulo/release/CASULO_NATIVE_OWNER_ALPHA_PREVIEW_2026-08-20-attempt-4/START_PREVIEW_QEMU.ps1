$ErrorActionPreference = "Stop"
$bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$image = Join-Path $bundle "casulo-native-owner-alpha-preview.img"
$qemu = "C:\Program Files\qemu\qemu-system-x86_64.exe"
$ovmfCode = "C:\Program Files\qemu\share\edk2-x86_64-code.fd"
$ovmfTemplate = "C:\Program Files\qemu\share\edk2-i386-vars.fd"
foreach ($dependency in @($image, $qemu, $ovmfCode, $ovmfTemplate)) {
  if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) { throw "Dependencia ausente: $dependency" }
}
$session = Join-Path $env:LOCALAPPDATA ("Casulo\native-preview\" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $session | Out-Null
$ovmfVars = Join-Path $session "OVMF_VARS.fd"
$serial = Join-Path $session "serial.log"
Copy-Item -LiteralPath $ovmfTemplate -Destination $ovmfVars
$qemuArgs = @(
  "-machine", "q35,accel=tcg", "-m", "256M", "-smp", "2",
  "-nic", "none", "-no-reboot", "-boot", "order=c,strict=on",
  "-device", "VGA",
  "-drive", "if=pflash,format=raw,unit=0,readonly=on,file=$ovmfCode",
  "-drive", "if=pflash,format=raw,unit=1,file=$ovmfVars",
  "-device", "qemu-xhci,id=casulo-xhci",
  "-drive", "if=none,id=casulo-usb,format=raw,readonly=on,file=$image",
  "-device", "usb-storage,bus=casulo-xhci.0,drive=casulo-usb,removable=true",
  "-serial", "file:$serial", "-monitor", "none"
)
Write-Host "Casulo Native preview: $image"
Write-Host "Serial append-only desta sessao: $serial"
Write-Host "Limite atual: superficie visual; sem conversa neural Native."
& $qemu @qemuArgs
