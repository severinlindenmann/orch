# The README's Windows install as a standard user (no admin, no git, default execution policy) in a winvm clone
# (ORCH-1127): the same script as the windows-standard-user job in workspace.yml, from the source in C:\ci\src.
param([Parameter(Mandatory)] [string]$Ref)
$ErrorActionPreference = "Stop"
$t = [Diagnostics.Stopwatch]::StartNew()
& "C:\ci\src\e2e\windows\run-as-standard-user.ps1" -Ref $Ref -Repo "C:\ci\src"
$rc = if ($?) { 0 } else { 1 }
"STEP standard-user $([int]$t.Elapsed.TotalSeconds)s rc=$rc" | Write-Host
exit $rc
