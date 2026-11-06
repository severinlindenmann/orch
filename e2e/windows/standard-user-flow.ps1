# A standard Windows user's first steps with orch, exactly as the README says: the one-line install (no admin, no
# git, default execution policy), then orch init, a ticket, an add-on and an update. Every result goes to the log;
# the last line is "RESULT ok" or "RESULT fail: <what>". Started by run-as-standard-user.ps1, never by hand.
# ORCH_REF (env) picks the branch or commit to install (or ORCH_REPO a local source folder); ORCH_INSTALL_PS1 (env) is the
# installer file to run.
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
$fails = @()
function L($m) { Add-Content -Path $log -Value $m }
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
"" | Set-Content $log
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
L "user: $(whoami)  admin: $admin  policy: $(Get-ExecutionPolicy)  arch: $env:PROCESSOR_ARCHITECTURE  ref: $env:ORCH_REF"
Check (-not $admin) "runs without admin rights"
Check (-not (Get-Command git -ErrorAction SilentlyContinue)) "git is not on PATH"

L "--- install"
try { Get-Content $env:ORCH_INSTALL_PS1 -Raw | Invoke-Expression *>&1 | Out-String | % { L $_ } } catch { L "install threw: $_" }
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
$v = orch --version 2>&1
L "version: $v"
Check ("$v" -match "^orch ") "orch --version"

# orch runs here as a script or an agent tool runs it: stdin is NUL. (The task's own hidden console is a real
# console, so orch would rightly ask its questions there, where nobody can answer.) NUL must never count as
# a person at a terminal: that is the Windows hang term.is_terminal fixes.
function O { cmd /c "orch $($args -join ' ') < NUL 2>&1" }
$p = "$env:USERPROFILE\orch-smoke"; New-Item -ItemType Directory -Force $p | Out-Null; Set-Location $p
L "--- init"; O init | Out-String | % { L $_ }
Check (Test-Path "$p\.agents\skills\orch\SKILL.md") "orch init wrote the skill"
Check ((Get-Item "$p\.claude\skills" -Force -ErrorAction SilentlyContinue).LinkType -eq "Junction") ".claude\skills is a junction"
$before = (Get-ChildItem -Recurse -Force -File | Get-FileHash | Out-String)
O init | Out-Null
Check ($before -eq (Get-ChildItem -Recurse -Force -File | Get-FileHash | Out-String)) "a second orch init changes nothing"

L "--- ticket"; $t = O ticket new '"Windows smoke"' --json | Out-String; L $t
Check ($LASTEXITCODE -eq 0) "orch ticket new"

L "--- addon add dashboard"; O addon add dashboard --yes | Out-String | % { L $_ }
Check ($LASTEXITCODE -eq 0) "orch addon add dashboard (installs from the zip, no git)"
L "--- update"; O update | Out-String | % { L $_ }
Check ($LASTEXITCODE -eq 0) "orch update"
$list = O addon list | Out-String; L $list
Check ($list -match "dashboard") "dashboard still installed after the update"

if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
