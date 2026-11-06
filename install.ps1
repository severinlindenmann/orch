# orch installer (Windows): installs uv if missing, then orch.
# ORCH_REPO / ORCH_REF override the source (default: GitHub main).
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv ..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
$repo = if ($env:ORCH_REPO) { $env:ORCH_REPO } else { "https://github.com/severinlindenmann/orch" }
$ref = if ($env:ORCH_REF) { $env:ORCH_REF } else { "main" }
if (Test-Path $repo) {
    $spec = Join-Path $repo "workspace"
} else {
    $spec = "git+$($repo -replace '\.git$','')@$ref#subdirectory=workspace"
}
uv tool install --reinstall $spec
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed" }
Write-Host "orch is installed."
$bin = "$env:USERPROFILE\.local\bin"
if (($env:Path -split ";") -notcontains $bin) {
    Write-Host "Run this line in PowerShell, then open a new terminal:"
    Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"$bin;`" + [Environment]::GetEnvironmentVariable('Path','User'), 'User')"
}
Write-Host "Then go to your project folder and run: orch init"
