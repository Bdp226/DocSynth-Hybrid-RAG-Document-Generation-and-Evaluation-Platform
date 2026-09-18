$ErrorActionPreference = 'Stop'

$ip = ([System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
  Where-Object {
    $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
    $_.IPAddressToString -notlike '127.*' -and
    $_.IPAddressToString -notlike '169.254.*'
  } |
  Select-Object -First 1)

if ($ip) {
  $ip = $ip.IPAddressToString
}

if (!$ip) {
  Write-Host 'Could not detect a LAN IPv4 address automatically.'
  Write-Host 'Use ipconfig and choose your active adapter IPv4 address.'
  exit 1
}

Write-Host "Local machine UI:   http://localhost:8080/ui/"
Write-Host "Network share UI:   http://${ip}:8080/ui/"
Write-Host "Network API docs:   http://${ip}:8080/docs"
Write-Host ''
Write-Host 'If colleagues cannot open the URL, ask IT to allow inbound TCP 8080 for your device.'
