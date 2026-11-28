# The automation add-on (the scheduler) on Windows, as a standard user: it runs in the background, starts the agent on a
# repeat ("every 5 minutes", the shortest a repeat may be) and at a one-time wake-up in a named time zone ("today HH:MM" --tz Europe/Zurich), and
# stops. The agent is the repo's fake one (e2e/fixtures/generic-agent): it finishes the first open task. Runs after
# standard-user-flow.ps1 (orch is installed); appends to the same log; ends with "RESULT ok" or "RESULT fail: ...".
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
$fails = @()
function L($m) { Add-Content -Path $log -Value $m }
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
function O { cmd /c "orch $($args -join ' ') < NUL 2>&1" }
function NewSmokeTicket($title) {
    # JSON is stdout only. Join native output lines before parsing (Windows PowerShell 5.1).
    # Keep stderr in the flow log, not in the JSON document.
    $out = cmd /c "orch ticket new `"$title`" --json --by human:owner < NUL 2>> `"$log`"" | Out-String
    if ($LASTEXITCODE -ne 0) { throw "ticket new failed for $title (exit $LASTEXITCODE): $out" }
    $ticket = ConvertFrom-Json -InputObject $out -ErrorAction Stop
    if (-not $ticket.id) { throw "ticket new returned no id for $title : $out" }
    $out = O check add $ticket.id '"Say hello"' --by human:owner | Out-String
    if ($LASTEXITCODE -ne 0) { throw "check add failed for $title : $out" }
    return $ticket.id
}
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
# One retry of the helper start (ORCH-2406): on a loaded VM the automation's `orch run start` once took longer than the
# 120 s it gets (the step took 758 s, 375 s when idle), and the automation asked "The helper could not start: orch could
# not be run (TimeoutExpired). (Try again / Leave it)". The flow then answers Try again ONCE, as a person would, and
# waits the same time again. A start that fails a second time, or any other reason, is a real failure.
function DoneWithin($tid, $sec) {
    $t0 = Get-Date; $retried = $false
    while (((Get-Date) - $t0).TotalSeconds -lt $sec) {
        $s = O ticket show $tid | Out-String
        if ($s -match '1 of 1 done') { return $true }
        if (-not $retried -and $s -match 'The helper could not start: orch could not be run \(TimeoutExpired\)[^\r\n]*\[(q\d+)\]') {
            $retried = $true; $q = $Matches[1]
            L "the helper start timed out once: answering Try again ($q), one retry"
            L (O answer $tid $q '"Try again"' --by human:owner | Out-String)
            if ($LASTEXITCODE -eq 0) { $t0 = Get-Date } else { L "the answer was refused (exit $LASTEXITCODE): no retry" }
        }
        Start-Sleep 5
    }
    L (O ticket show $tid | Out-String); return $false
}
L ""
L "=== scheduler (automation add-on)"
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
$env:ORCH_AGENT = ""
$p = "$env:USERPROFILE\.orch-test\orch-sched"; New-Item -ItemType Directory -Force $p | Out-Null; Set-Location $p
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

try {
    $rep = NewSmokeTicket "Scheduled smoke"
    $one = NewSmokeTicket "Wake-up smoke"
} catch {
    L "RESULT fail: scheduler setup: $($_.Exception.Message)"
    return  # no background service or long waits with missing tickets
}
L (O automation repeat $rep '"every 5 minutes"' | Out-String)
Check ($LASTEXITCODE -eq 0) "a repeat: every 5 minutes"

$zurich = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date).AddMinutes(3), "W. Europe Standard Time")
$at = $zurich.ToString("HH:mm")
$zurichNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "W. Europe Standard Time")
$day = if ($zurich.Date -ne $zurichNow.Date) { "tomorrow" } else { "today" }  # near midnight "today HH:mm" would already be past
L (O automation repeat $one ('"' + $day + ' ' + $at + '"') --tz Europe/Zurich | Out-String)
Check ($LASTEXITCODE -eq 0) "a one-time wake-up in a named time zone ($day $at Europe/Zurich)"
L (O automation list | Out-String)

L "--- start"; L (O start --no-open | Out-String)
Check ((O automation status | Out-String) -match 'run' -and $LASTEXITCODE -eq 0) "automation runs in the background"
Check (DoneWithin $rep 420) "the repeat started the agent and the task got done"
Check (DoneWithin $one 300) "the one-time wake-up started the agent and the task got done"
L (O needs | Out-String)

L (O automation repeat $rep --off | Out-String)
L "--- stop"; L (O stop | Out-String)
O automation status | Out-Null
Check ($LASTEXITCODE -ne 0) "automation stopped (status exit 1)"

if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
