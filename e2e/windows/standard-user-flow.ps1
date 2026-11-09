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
# Windows can not replace orch while it runs: add-on installs and updates finish in the background once the
# command has ended (winfinish.py). Wait for the finisher's RESULT line in the log the command printed.
# Only RESULT lines after $since (the log's RESULT count before the command) count: the log is shared.
function Results($out) {
    $m = [regex]::Match("$out", 'Log: (\S+)')
    if (-not $m.Success) { return @() }
    @(Get-Content $m.Groups[1].Value -ErrorAction SilentlyContinue | Select-String '^\S+ \S+ RESULT ')
}
function WaitFinish($out, $what, $since) {
    if (-not [regex]::IsMatch("$out", 'Log: (\S+)')) { return $true }  # finished in the command itself
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 600) {
        $last = Results $out | Select -Skip $since | Select -Last 1
        if ($last) { L "finisher ($what): $last"; return ("$last" -match 'RESULT ok') }
        Start-Sleep 3
    }
    L "finisher ($what): no RESULT after 10 min"; return $false
}
$env:ORCH_AGENT = "claude"  # links .claude\skills (no agent is installed here; CI does the same)
$p = "$env:USERPROFILE\orch-smoke"; New-Item -ItemType Directory -Force $p | Out-Null; Set-Location $p
L "--- init"; O init | Out-String | % { L $_ }
Check (Test-Path "$p\.agents\skills\orch\SKILL.md") "orch init wrote the skill"
Check (((Get-Item "$p\.claude\skills\orch" -Force -ErrorAction SilentlyContinue).LinkType -eq "Junction") -or (Test-Path "$p\.claude\skills\orch\.orch-copy")) ".claude\skills\orch is a junction (or a copy where links are refused)"
Check (Test-Path "$p\.claude\skills\orch\SKILL.md") "the skill is found through .claude\skills"
Check ((-not (Test-Path "$p\AGENTS.md")) -and (-not (Test-Path "$p\CLAUDE.md")) -and (-not (Test-Path "$p\.gitignore"))) "init wrote no team file"
$before = (Get-ChildItem -Recurse -Force -File | Get-FileHash | Out-String)
O init | Out-Null
Check ($before -eq (Get-ChildItem -Recurse -Force -File | Get-FileHash | Out-String)) "a second orch init changes nothing"

L "--- ticket"; $t = O ticket new '"Windows smoke"' --json | Out-String; L $t
Check ($LASTEXITCODE -eq 0) "orch ticket new"

L "--- addon add dashboard"; $out = O addon add dashboard --yes | Out-String; L $out
Check ($LASTEXITCODE -eq 0) "orch addon add dashboard (installs from the zip, no git)"
Check (WaitFinish $out "addon add" 0) "dashboard install finished"
$since = (Results $out).Count
L "--- update"; $out = O update | Out-String; L $out
if ($LASTEXITCODE -ne 0 -and $out -match "dashboard on this computer|Waiting for your click") {
    # a person's action (H1): the scripted test human proves it in a dev demo workspace
    $proof = (cmd /c "orch dev-proof update orch 2>NUL" | Out-String).Trim()
    Check ($proof.StartsWith("hp1.")) "test-human proof for orch update"
    $out = $proof | cmd /c "orch update --proof-stdin 2>&1" | Out-String; L $out
}
Check ($LASTEXITCODE -eq 0) "orch update"
Check (WaitFinish $out "update" $since) "update finished"
Check ("$(O --version)" -match "^orch ") "orch still runs after the update"
$list = O addon list | Out-String; L $list
Check ($list -match "dashboard") "dashboard still installed after the update"
Check (Test-Path "$p\.agents\skills\orch-dashboard") "dashboard skill in the workspace"

L "--- dashboard in the background"; $out = O start --no-open --json | Out-String; L $out
$url = [regex]::Match($out, 'http://127\.0\.0\.1:\d+').Value
Check ([bool]$url) "orch start runs the dashboard"
# The run folder is private, and this user is in its ACL by SID (#168: granted from the process token)
$sid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$acl = cmd /c "icacls `"$p\.orch\run\dashboard`" 2>&1" | Out-String; L $acl
$name = ([Security.Principal.SecurityIdentifier]$sid).Translate([Security.Principal.NTAccount]).Value
Check ($acl -match [regex]::Escape($name) -and $acl -notmatch 'Everyone|BUILTIN\\Users') "the dashboard's run folder is private and this user is granted (#168)"
$state = $null
if ($url) {
    foreach ($i in 1..20) {
        try { $state = (Invoke-WebRequest "$url/api/state" -UseBasicParsing -TimeoutSec 5).Content; break } catch { Start-Sleep 1 }
    }
}
Check ("$state" -match "Windows smoke") "the dashboard shows the ticket"
$again = O start --no-open | Out-String; L $again
Check ($LASTEXITCODE -eq 0 -and $again -match [regex]::Escape($url)) "a second orch start keeps the running dashboard"
L "--- stop"; L (O stop | Out-String)
Check ($LASTEXITCODE -eq 0) "orch stop"
$restart = O start --no-open | Out-String; L $restart
Check ($LASTEXITCODE -eq 0 -and $restart -match "127\.0\.0\.1") "the dashboard starts again after a stop"
O stop | Out-Null

if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
