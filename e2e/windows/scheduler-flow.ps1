# The automation add-on (the scheduler) on Windows, as a standard user: it runs in the background, starts the agent on a
# repeat ("every 1 minutes") and at a one-time wake-up in a named time zone ("today HH:MM" --tz Europe/Zurich), and
# stops. The agent is the repo's fake one (e2e/fixtures/generic-agent): it finishes the first open task. Runs after
# standard-user-flow.ps1 (orch is installed); appends to the same log; ends with "RESULT ok" or "RESULT fail: ...".
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
$fails = @()
function L($m) { Add-Content -Path $log -Value $m }
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
function O { cmd /c "orch $($args -join ' ') < NUL 2>&1" }
function Results($out) {
    $m = [regex]::Match("$out", 'Log: (\S+)')
    if (-not $m.Success) { return @() }
    @(Get-Content $m.Groups[1].Value -ErrorAction SilentlyContinue | Select-String '^\S+ \S+ RESULT ')
}
# The finish log is shared with the earlier flow: only RESULT lines stamped at or after $from count.
function WaitFinish($out, $from) {
    if (-not [regex]::IsMatch("$out", 'Log: (\S+)')) { return $true }
    $stamp = $from.ToString("yyyy-MM-dd HH:mm:ss")
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 600) {
        $last = Results $out | Where-Object { "$_".Substring(0, 19) -ge $stamp } | Select -Last 1
        if ($last) { L "finisher: $last"; return ("$last" -match 'RESULT ok') }
        Start-Sleep 3
    }
    return $false
}
function DoneWithin($tid, $sec) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $sec) {
        $s = O ticket show $tid | Out-String
        if ($s -match '1 of 1 done') { return $true }
        Start-Sleep 5
    }
    L (O ticket show $tid | Out-String); return $false
}
L ""
L "=== scheduler (automation add-on)"
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
$env:ORCH_AGENT = ""
$p = "$env:USERPROFILE\orch-sched"; New-Item -ItemType Directory -Force $p | Out-Null; Set-Location $p
O init | Out-Null
$before = Get-Date; $out = O addon add automation --yes | Out-String; L $out
Check ($LASTEXITCODE -eq 0) "orch addon add automation"
Check (WaitFinish $out $before) "automation install finished"

# the fake agent, run by the Python orch itself runs on
$py = Join-Path (cmd /c "uv tool dir 2>NUL") "orch-workspace\Scripts\python.exe"
$agent = "C:\Users\Public\orchsmoke\agent.py"
L (cmd /c "orch config agent add fake --command `"$py $agent`" < NUL 2>&1" | Out-String)
L (O config agent fake | Out-String)
Check ($LASTEXITCODE -eq 0) "a custom agent (the fake one) is chosen"

$rep = ((O ticket new '"Scheduled smoke"' --json --by human:owner) | ConvertFrom-Json).id
O check add $rep '"Say hello"' --by human:owner | Out-Null
L (O automation repeat $rep '"every 1 minutes"' | Out-String)
Check ($LASTEXITCODE -eq 0) "a repeat: every 1 minutes"

$one = ((O ticket new '"Wake-up smoke"' --json --by human:owner) | ConvertFrom-Json).id
O check add $one '"Say hello"' --by human:owner | Out-Null
$zurich = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date).AddMinutes(3), "W. Europe Standard Time")
$at = $zurich.ToString("HH:mm")
L (O automation repeat $one ('"today ' + $at + '"') --tz Europe/Zurich | Out-String)
Check ($LASTEXITCODE -eq 0) "a one-time wake-up in a named time zone (today $at Europe/Zurich)"
L (O automation list | Out-String)

L "--- start"; L (O start --no-open | Out-String)
Check ((O automation status | Out-String) -match 'run' -and $LASTEXITCODE -eq 0) "automation runs in the background"
Check (DoneWithin $rep 180) "the repeat started the agent and the task got done"
Check (DoneWithin $one 300) "the one-time wake-up started the agent and the task got done"
L (O needs | Out-String)

L (O automation repeat $rep --off | Out-String)
L "--- stop"; L (O stop | Out-String)
O automation status | Out-Null
Check ($LASTEXITCODE -ne 0) "automation stopped (status exit 1)"

if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
