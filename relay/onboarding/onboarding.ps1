# orch relay onboarding (Windows): installs orch if it is missing, then connects this folder to the relay.
# Usage: & ([scriptblock]::Create((irm __RELAY_URL__/onboarding.ps1))) -Workspace ws_xxxxxxxxxx -Token orn_...
param(
  [Parameter(Mandatory = $true)][string]$Workspace,
  [Parameter(Mandatory = $true)][string]$Token
)
$ErrorActionPreference = 'Stop'
$RelayUrl = '__RELAY_URL__'
if (-not (Get-Command orch -ErrorAction SilentlyContinue)) {
  Write-Host 'orch is not installed yet. Installing it...'
  irm https://raw.githubusercontent.com/severinlindenmann/orch/main/install.ps1 | iex
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
orch relay connect $RelayUrl --workspace $Workspace --token $Token
