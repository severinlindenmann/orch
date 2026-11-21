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
$t = [Diagnostics.Stopwatch]::StartNew()
uv sync --python $Python
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
"STEP sync $([int]$t.Elapsed.TotalSeconds)s" | Write-Host
$t.Restart()
uv run pytest -q -n $Workers --part $Part --budget 180 --timeout-method thread --junitxml C:\ci\junit.xml
$rc = $LASTEXITCODE
"STEP pytest $([int]$t.Elapsed.TotalSeconds)s rc=$rc" | Write-Host
exit $rc
