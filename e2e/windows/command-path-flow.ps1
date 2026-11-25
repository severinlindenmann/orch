# Which orch a person reaches after the Windows install (ORCH-2101). Four windows, each a fresh PowerShell process:
# uv's default command folder; a custom one (UV_TOOL_BIN_DIR, with a space, an umlaut and an apostrophe); a custom one
# with an older orch.exe first on Path; and a uv that names a folder without orch.exe. In each window the installer
# runs, the line it suggests (if any) is run as printed, then `orch --version` shows which orch really starts.
# Started by run-as-standard-user.ps1 -Flows command-path, never by hand. ORCH_INSTALL_PS1 (env) is the installer to
# test, ORCH_REPO (env) the source. Transcripts go to ~\orch-shots (the harness copies them out).
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
if (-not (Test-Path $log)) { "" | Set-Content $log -Encoding UTF8 }
$fails = @()
function L($m) { Add-Content -Path $log -Value $m -Encoding UTF8 }
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
L "--- command path  user: $(whoami)  admin: $admin  installer: $env:ORCH_INSTALL_PS1"
Check (-not $admin) "runs without admin rights"
$env:ORCH_INSTALL_KIND = "test"
$shots = "$env:USERPROFILE\orch-shots"; New-Item -ItemType Directory -Force $shots | Out-Null
$base = $env:Path
$dflt = "$env:USERPROFILE\.local\bin"
# Kept ASCII here (Windows PowerShell reads this file as ANSI): "Zoe's tools" with an e-umlaut.
$custom = "$env:USERPROFILE\Zo$([char]0x00EB)'s tools\bin"
$old = "$env:USERPROFILE\old orch"; New-Item -ItemType Directory -Force $old | Out-Null
$empty = "$env:USERPROFILE\empty bin"; New-Item -ItemType Directory -Force $empty | Out-Null
try {
    Add-Type -OutputType ConsoleApplication -OutputAssembly "$old\orch.exe" -TypeDefinition @'
public static class OldOrch { public static void Main(string[] a) { System.Console.WriteLine("orch 0.0.1 (an older copy)"); } }
'@
} catch { L "could not build the older orch.exe: $_" }
Check (Test-Path "$old\orch.exe") "an older orch.exe to put first on Path"

# One window: runs in its own powershell.exe so its Path is only what this test gives it.
$window = @'
$ErrorActionPreference = "Continue"
$env:Path = $env:F_PATH
if ($env:F_BIN) { $env:UV_TOOL_BIN_DIR = $env:F_BIN }
if ($env:F_FAKEBIN) {
    $global:uvexe = (Get-Command uv -CommandType Application | Select-Object -First 1).Source
    function global:uv { if ($args -contains "--bin") { $env:F_FAKEBIN; $global:LASTEXITCODE = 0 } else { & $global:uvexe @args } }
}
$p = "PS $env:USERPROFILE>"
$all = New-Object System.Collections.Generic.List[string]
$threw = ""
try { Get-Content $env:ORCH_INSTALL_PS1 -Raw | Invoke-Expression *>&1 | ForEach-Object { $all.Add("$_") } }
catch { $threw = $_.Exception.Message; $all.Add($threw) }
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$t = New-Object System.Collections.Generic.List[string]
$t.Add("$p irm https://github.com/severinlindenmann/orch/raw/main/install.ps1 | iex")
$t.Add("...")
$from = [Math]::Max(0, $all.FindIndex([Predicate[string]] { param($x) $x -match '^(Installed \d+ executable|orch install stopped)' }))
foreach ($x in $all.GetRange($from, $all.Count - $from)) { $t.Add($x) }
$line = ""
for ($k = 0; $k -lt $all.Count - 1; $k++) {
    if ($all[$k] -match "run this line" -and $all[$k].TrimEnd().EndsWith(":")) { $line = $all[$k + 1].Trim(); break }
}
if ($line) { $t.Add("$p $line"); try { Invoke-Expression $line } catch { $t.Add("$_") } }
$cmd = Get-Command orch -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$src = if ($cmd) { $cmd.Source } else { "" }
$t.Add("$p orch --version")
try { $ver = (& orch --version 2>&1 | Out-String).Trim() } catch { $ver = $_.Exception.Message }
$t.Add($ver)
$t.Add("$p (Get-Command orch).Source")
$t.Add($(if ($src) { $src } else { "(no orch)" }))
$t | Set-Content -Encoding UTF8 $env:F_OUT
$all | Set-Content -Encoding UTF8 ($env:F_OUT -replace '\.txt$', '.full.txt')
[ordered]@{ line = $line; src = $src; ver = $ver; threw = $threw; userPathSame = ($userPath -eq $env:F_USERPATH)
    out = ($all -join "`n") } | ConvertTo-Json | Set-Content -Encoding UTF8 ($env:F_OUT -replace '\.txt$', '.json')
'@
$enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($window))
function Window($name, $path, $bin = "", $fakeBin = "") {
    $env:F_PATH = $path; $env:F_BIN = $bin; $env:F_FAKEBIN = $fakeBin; $env:F_OUT = "$shots\$name.txt"
    $env:F_USERPATH = [Environment]::GetEnvironmentVariable("Path", "User")
    powershell -NoProfile -NonInteractive -EncodedCommand $enc *>&1 | Out-Null
    $r = Get-Content "$shots\$name.json" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue | ConvertFrom-Json
    L "--- $name"; L (Get-Content "$shots\$name.txt" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue)
    $r
}
function Fresh($ver) { "$ver" -match '^orch ' -and "$ver" -notmatch '0\.0\.1' }
function NoNewWindowClaim($out) { "$out" -notmatch 'new (terminal|window)' -or "$out" -match 'not other or new windows' }

# 1. uv's default folder (uv itself is installed by the installer, which puts its folder first in this window)
$r = Window "default" $base
Check ((-not $r.line) -and $r.src -eq "$dflt\orch.exe" -and (Fresh $r.ver)) "default folder: no extra line, plain orch is the installed one"
Check ("$($r.out)" -match 'orch is installed\.' -and "$($r.out)" -match 'run: orch init') "default folder: the usual end, then orch init"
$withUv = "$dflt;$base"
# 2. a custom folder; the default copy is removed so no other orch is on Path
Remove-Item "$dflt\orch.exe" -Force -ErrorAction SilentlyContinue
$r = Window "custom" $withUv $custom
Check ($r.line -and $r.src -eq "$custom\orch.exe" -and (Fresh $r.ver)) "custom folder: the suggested line makes plain orch the installed one"
Check ($r.userPathSame -and (NoNewWindowClaim $r.out)) "custom folder: saved Path unchanged, no claim about new windows"
# 3. an older orch.exe first on Path
$r = Window "older" "$old;$withUv" $custom
Check ("$($r.out)" -match [regex]::Escape("another orch: $old\orch.exe")) "older copy first: the installer names it"
Check ($r.line -and $r.src -eq "$custom\orch.exe" -and (Fresh $r.ver)) "older copy first: after the suggested line the new orch runs"
Check ($r.userPathSame) "older copy first: saved Path unchanged"
# 4. uv names a folder without orch.exe
$r = Window "missing" $withUv $custom $empty
Check ($r.threw -and "$($r.out)" -notmatch 'orch is installed' -and -not $r.line) "missing orch.exe: stops, no success and no line to run"
Check ($r.userPathSame) "missing orch.exe: saved Path unchanged"

if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
