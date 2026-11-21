# Windows CLI smoke in a winvm clone (ORCH-1127): the steps of cli-smoke.yml - the real installer from this
# source, then e2e/ci/cli-smoke.sh in Git Bash. Runs after setup.ps1.
$ErrorActionPreference = "Stop"
$src = "C:\ci\src"
$env:ORCH_HOME = "$env:USERPROFILE\.orch-test\smoke-home"; $env:ORCH_HOME_STRICT = "1"
New-Item -ItemType Directory -Force $env:ORCH_HOME | Out-Null
$env:ORCH_REPO = $src; $env:ORCH_INSTALL_KIND = "test"
$t = [Diagnostics.Stopwatch]::StartNew()
& "$src\install.ps1"
"STEP install $([int]$t.Elapsed.TotalSeconds)s" | Write-Host
$t.Restart()
Set-Location $src
bash -c 'export PATH="$HOME/.local/bin:$PATH"; bash e2e/ci/cli-smoke.sh focus'
$rc = $LASTEXITCODE
"STEP smoke $([int]$t.Elapsed.TotalSeconds)s rc=$rc" | Write-Host
exit $rc
