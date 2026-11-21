# Windows CLI smoke in a winvm clone (ORCH-1127): the steps of cli-smoke.yml - the real installer from this
# source, then e2e/ci/cli-smoke.sh in Git Bash. Runs after setup.ps1.
$ErrorActionPreference = "Stop"
$src = "C:\ci\src"
$env:ORCH_HOME = "$env:USERPROFILE\.orch-test\smoke-home"; $env:ORCH_HOME_STRICT = "1"
New-Item -ItemType Directory -Force $env:ORCH_HOME | Out-Null
$env:ORCH_REPO = $src; $env:ORCH_INSTALL_KIND = "test"
# Windows PowerShell 5.1 with "Stop" turns any line a program writes to stderr (progress, warnings) into a
# fatal error: run programs through Invoke-Native, which judges them by their exit code only.
function Invoke-Native {
    $ErrorActionPreference = "Continue"
    & $args[0] @($args | Select-Object -Skip 1) 2>&1 | ForEach-Object { "$_" } | Write-Host
    return $LASTEXITCODE
}
$t = [Diagnostics.Stopwatch]::StartNew()
$ErrorActionPreference = "Continue"  # install.ps1 checks its own steps; uv writes progress to stderr
& "$src\install.ps1"
if (-not $?) { throw "install.ps1 failed" }
"STEP install $([int]$t.Elapsed.TotalSeconds)s" | Write-Host
# before the smoke: cli-smoke.sh ends with `orch uninstall`
# The junction check of workspace.yml: .claude\skills holds one link per skill (a copy where links are refused, #215).
$d = "C:\ci\junction"; New-Item -ItemType Directory -Force $d | Out-Null; Set-Location $d
$jrc = 0
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"; $env:ORCH_AGENT = "claude"
$null = Invoke-Native orch init
$item = Get-Item "$d\.claude\skills\orch" -Force -ErrorAction SilentlyContinue
if (-not $item -or ($item.LinkType -ne "Junction" -and -not (Test-Path "$d\.claude\skills\orch\.orch-copy"))) {
    "junction check: expected .claude\skills\orch to be a junction, got '$($item.LinkType)'" | Write-Host
    $jrc = 1
} else { "junction check ok" | Write-Host }
$t.Restart()
Set-Location $src
$rc = Invoke-Native bash -c 'export PATH="$HOME/.local/bin:$PATH"; bash e2e/ci/cli-smoke.sh focus'
"STEP smoke $([int]$t.Elapsed.TotalSeconds)s rc=$rc" | Write-Host
if ($jrc -ne 0 -and $rc -eq 0) { $rc = 1 }
exit $rc
