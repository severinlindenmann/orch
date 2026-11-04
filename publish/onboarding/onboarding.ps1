# Connects this project to orch-publish. Installs orch first if it is missing.
# Usage: & ([scriptblock]::Create((irm __PUBLISH_URL__/onboarding.ps1))) -Workspace ws_xxx -Token orp_xxx
param([Parameter(Mandatory = $true)][string]$Workspace, [Parameter(Mandatory = $true)][string]$Token)
$ErrorActionPreference = "Stop"
$Url = "__PUBLISH_URL__"
$InstallUrl = "__INSTALL_URL__"
if (-not (Get-Command orch -ErrorAction SilentlyContinue)) {
  Write-Host "Installing orch ..."
  $env:ORCH_REF = "__INSTALL_REF__"
  & ([scriptblock]::Create((irm ($InstallUrl -replace '\.sh$', '.ps1'))))
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
orch publish connect $Url --workspace $Workspace --token $Token
