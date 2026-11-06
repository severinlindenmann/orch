# orch installer (Windows): installs uv if missing, then orch.
# ORCH_REPO / ORCH_REF override the source (default: GitHub main).
# Works for a standard user: no admin rights, no git, no change to the execution policy.
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv ..."
    # A fresh Windows refuses scripts (execution policy Restricted); allow them for this one process only.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) { throw "uv install failed" }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
$repo = if ($env:ORCH_REPO) { $env:ORCH_REPO } else { "https://github.com/severinlindenmann/orch" }
$ref = if ($env:ORCH_REF) { $env:ORCH_REF } else { "main" }
$r = $repo -replace '\.git$',''
if (Test-Path $repo) {
    $spec = Join-Path $repo "workspace"
} elseif ($r -like "https://github.com/*") {
    $spec = "$r/archive/$ref.zip#subdirectory=workspace"  # a zip download: no git needed
} else {
    $spec = "git+$r@$ref#subdirectory=workspace"
}
$py = @()
$arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($arch -eq "ARM64") {
    # cryptography ships no ARM64 Windows build; an x64 Python runs it through Windows' built-in emulation.
    $py = @("--python", "cpython-3.13-windows-x86_64-none")
}
uv tool install --reinstall --refresh @py $spec
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed" }
# Put back the add-ons this machine had (the reinstall above drops them); nothing happens on a first install.
$toolBin = (uv tool dir --bin)
& (Join-Path $toolBin "orch.exe") update --after-install
if ($LASTEXITCODE -ne 0) { Write-Host "Note: your add-ons could not be installed again. Run: orch update" }
Write-Host "orch is installed."
$bin = "$env:USERPROFILE\.local\bin"
if (($env:Path -split ";") -notcontains $bin) {
    Write-Host "Run this line in PowerShell, then open a new terminal:"
    Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"$bin;`" + [Environment]::GetEnvironmentVariable('Path','User'), 'User')"
}
Write-Host "Then go to your project folder and run: orch init"
