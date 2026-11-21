# Workspace tests in a winvm clone (ORCH-1127), the same flags as the Windows job in workspace.yml.
# Runs after setup.ps1. -Part K/N runs every N-th test (ci_parts.py); default: the whole suite.
param(
    [string]$Part = "1/1",
    [string]$Python = "cpython-3.13-windows-x86_64-none",
    [int]$Workers = 4
)
$ErrorActionPreference = "Stop"
Set-Location "C:\ci\src\workspace"
# orch's safe git refuses a python inside the project folder: keep the venv outside (ORCH-32, workspace.yml).
$env:UV_PROJECT_ENVIRONMENT = "C:\ci\venv"
# orch's per-machine folder is a throwaway one, never the real ~/.orch-tool.
$env:ORCH_HOME = "C:\ci\orch-home"; $env:ORCH_HOME_STRICT = "1"
New-Item -ItemType Directory -Force $env:ORCH_HOME | Out-Null
# Windows PowerShell 5.1 with "Stop" turns any line a program writes to stderr (progress, warnings) into a
# fatal error: run programs through Invoke-Native, which judges them by their exit code only.
function Invoke-Native {
    $ErrorActionPreference = "Continue"
    & $args[0] @($args | Select-Object -Skip 1) 2>&1 | ForEach-Object { "$_" } | Write-Host
    return $LASTEXITCODE
}
$t = [Diagnostics.Stopwatch]::StartNew()
if ((Invoke-Native uv sync --python $Python) -ne 0) { throw "uv sync failed" }
"STEP sync $([int]$t.Elapsed.TotalSeconds)s" | Write-Host
$t.Restart()
$rc = Invoke-Native uv run pytest -q -n $Workers --part $Part --budget 180 --timeout-method thread --junitxml C:\ci\junit.xml
"STEP pytest $([int]$t.Elapsed.TotalSeconds)s rc=$rc" | Write-Host
exit $rc
