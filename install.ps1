param([string]$InstallKind = "normal")
if ($env:ORCH_INSTALL_KIND -and $PSBoundParameters.Count -eq 0) { $InstallKind = $env:ORCH_INSTALL_KIND }
if ($InstallKind -notin @("normal","dev","test")) { throw "InstallKind must be normal, dev or test." }
# orch installer (Windows): installs uv if missing, then orch.
# ORCH_REPO / ORCH_REF override the source (default: GitHub main).
# To leave: `orch uninstall` in a project (your tickets stay), then `uv tool uninstall orch-workspace`.
# -InstallKind test|dev (given by the person running this installer) marks a test or dev install; default normal.
# Works for a standard user: no admin rights, no git, no change to the execution policy.
# Not "Stop": Windows PowerShell turns a native tool's stderr (uv's progress lines) into errors when the output is
# redirected, which would abort the install. Every native call is checked by its exit code instead.
$ErrorActionPreference = "Continue"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv ..."
    # A fresh Windows refuses scripts (execution policy Restricted); allow them for this one process only.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    # Name the step that stopped and one thing to try; uv's own messages stay above, its exit code stays in the text.
    if ($LASTEXITCODE -ne 0) {
        throw "orch install stopped while setting up uv, the tool that installs orch (exit code $LASTEXITCODE; its details are above). Next: install uv yourself from https://docs.astral.sh/uv/getting-started/installation/, then run the install line again in a new PowerShell window."
    }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
$repo = if ($env:ORCH_REPO) { $env:ORCH_REPO } else { "https://github.com/severinlindenmann/orch" }
$ref = if ($env:ORCH_REF) { $env:ORCH_REF } else { "main" }
$r = $repo -replace '\.git$',''
# A ref is a plain git ref name: in a zip URL a '../' or '#' could reach another repository or folder.
if ($ref -notmatch '\A[A-Za-z0-9._/-]+\z' -or $ref -match '\.\.' -or $ref -match '^[-/]' -or $ref -match '(\.lock|/)$') {
    throw "'$ref' is not a branch, tag or commit name (check ORCH_REF)."
}
if (-not (Test-Path $repo) -and $r -match '[\s"''#?]') { throw "'$r' is not a repository address (check ORCH_REPO)." }
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
if ($LASTEXITCODE -ne 0) {
    throw "orch install stopped while installing orch with uv (exit code $LASTEXITCODE; its details are above). Next: read uv's lines above for the reason, then run the install line again."
}
# The install record is written here, by this installer, into orch's own tool environment (no orch command does).
$toolDir = Join-Path (uv tool dir) "orch-workspace"
$record = [ordered]@{ kind = $InstallKind; root = (Resolve-Path $toolDir).Path; schema = "orch.install/1" } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText((Join-Path $toolDir "orch-install.json"), $record + "`n")
if ($InstallKind -ne "normal") { Write-Host "*** $($InstallKind.ToUpper()) INSTALL: this orch is marked as a $InstallKind install. ***" }
# Put back the add-ons this machine had (the reinstall above drops them); nothing happens on a first install.
$toolBin = (uv tool dir --bin)
if ($LASTEXITCODE -ne 0 -or -not $toolBin) { throw "uv tool dir failed" }
$orchExe = Join-Path $toolBin "orch.exe"
& $orchExe update --after-install
$restoreFailed = $LASTEXITCODE -ne 0
if ($restoreFailed) {
    # orch itself is in place; only putting the add-ons back stopped (orch's own reason is above, on stderr).
    Write-Host "orch is installed, but putting your add-ons back did not finish (the reason is above)."
} else {
    Write-Host "orch is installed."
}
$bin = "$env:USERPROFILE\.local\bin"
if (($env:Path -split ";") -notcontains $bin) {
    Write-Host "Run this line in PowerShell, then open a new terminal:"
    Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"$bin;`" + [Environment]::GetEnvironmentVariable('Path','User'), 'User')"
    $go = "Then go to your project folder and run"
} else {
    $go = "Open a new terminal, go to your project folder and run"
}
if ($restoreFailed) {
    # A returning person already has a project: the one next step is the update there, never a fresh init.
    # By name only when "orch" already runs this installed copy; else the full path, quoted for PowerShell
    # (an apostrophe, also a typographic one, is doubled inside single quotes).
    $found = Get-Command orch -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $byName = $found -and ([IO.Path]::GetFullPath((Split-Path $found.Source)).TrimEnd('\', '/') -eq [IO.Path]::GetFullPath($toolBin).TrimEnd('\', '/'))
    $run = if ($byName) { "orch update" } else { "& '" + ($orchExe -replace "['\u2018\u2019\u201A\u201B]", '$0$0') + "' update" }
    Write-Host "$go this to put your add-ons back:"
    Write-Host "  $run"
} else {
    Write-Host "$go one of these:"
    Write-Host "  orch init                  local tickets: enough to start"
    Write-Host "  orch init --recommended    the same, plus the dashboard (optional; asks first)"
}
