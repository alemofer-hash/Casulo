[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

Write-Host 'CASULO NETWORK DIAGNOSTIC — READ ONLY' -ForegroundColor Cyan

Write-Host "`n=== Network profiles ==="
Get-NetConnectionProfile |
    Select-Object Name, InterfaceAlias, NetworkCategory, IPv4Connectivity, IPv6Connectivity

Write-Host "`n=== IPv4 addresses ==="
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.AddressState -eq 'Preferred' } |
    Select-Object InterfaceAlias, IPAddress, PrefixLength, Type

Write-Host "`n=== Reserved ports ==="
$ports = 8443, 8081, 8082, 8083, 8084
$connections = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object LocalPort -in $ports |
    Select-Object LocalAddress, LocalPort, OwningProcess)
if ($connections.Count -eq 0) { Write-Host 'No reserved port is listening.' } else { $connections | Format-Table -AutoSize }

Write-Host "`n=== Exposure rule ==="
Write-Host 'Expected after deployment:'
Write-Host '  8443 -> selected LAN interface/subnet'
Write-Host '  8081-8084 -> 127.0.0.1 only'
Write-Host 'Any 8081-8084 binding on 0.0.0.0, ::, or a LAN address is a release blocker.'

Write-Host "`n=== Existing Casulo firewall rules ==="
$rules = @(Get-NetFirewallRule -ErrorAction SilentlyContinue |
    Where-Object DisplayName -like 'Casulo*' |
    Select-Object DisplayName, Enabled, Direction, Action, Profile)
if ($rules.Count -eq 0) { Write-Host 'No Casulo firewall rules found.' } else { $rules | Format-Table -AutoSize }

Write-Host "`nNo network configuration was changed." -ForegroundColor Green

