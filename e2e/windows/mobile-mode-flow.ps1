# Run as the logged-in desktop user; the caller wraps each phase in a separate scheduled task.
# Mobile mode needs the relay add-on on, not a relay connection (heartbeats just fail quietly), so no relay settings.
# End the start task/shell before running -Phase check, then run -Phase off in the same user profile.
param([ValidateSet('start','check','off')][string]$Phase = 'start')
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
$fails = @()
function L($m) {
    # Redact at the log boundary, including installer output and unexpected errors.
    $text = "$m"
    if ($env:E2E_RELAY_TOKEN) { $text = $text.Replace($env:E2E_RELAY_TOKEN, "<token>") }
    Add-Content -Path $log -Value $text
}
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
function O { cmd /c "orch $($args -join ' ') < NUL 2>&1" }
function Results($path) { @(Get-Content $path -ErrorAction SilentlyContinue | Select-String '^\S+ \S+ RESULT ') }
function WaitFinish($out, $since) {
    $m = [regex]::Match("$out", 'Log: (\S+)')
    if (-not $m.Success) { return $true }
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 600) {
        $last = Results $m.Groups[1].Value | Select -Skip $since | Select -Last 1
        if ($last) { L "finisher: $last"; return ("$last" -match 'RESULT ok') }
        Start-Sleep 3
    }
    return $false
}
function PowerRequests($expected, $processName) {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { L "powercfg needs admin: run by the caller"; return }
    $out = powercfg /requests 2>&1 | Out-String
    $rc = $LASTEXITCODE; L $out
    Check ($rc -eq 0) "powercfg /requests"
    if ($rc -ne 0) { return }
    # powercfg reports executable paths, not PIDs. Match the keeper's executable in the relevant sections.
    $section = ""; $found = $false
    foreach ($line in ($out -split '\r?\n')) {
        if ($line -match '^\s*([A-Z]+):\s*$') { $section = $Matches[1] }
        if ($section -in @('SYSTEM', 'EXECUTION') -and
            $line -match ('(?i)\[PROCESS\].*[\\/]' + [regex]::Escape($processName) + '\s*$')) {
            $found = $true
        }
    }
    Check ($found -eq $expected) "keeper executable $processName in SYSTEM or EXECUTION: $expected"
}

L ""; L "=== mobile mode ($Phase)"
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
$pidFile = "$env:USERPROFILE\mm-keeper.pid"
$contextFile = "$env:USERPROFILE\mm-keeper.json"
try {
    if (-not (Get-Command orch -ErrorAction SilentlyContinue)) {
        L "--- install"
        Get-Content $env:ORCH_INSTALL_PS1 -Raw -ErrorAction Stop | Invoke-Expression *>&1 | Out-String | % { L $_ }
    }
    if (-not (Get-Command orch -ErrorAction SilentlyContinue)) { throw "orch is missing after install" }
    if ($Phase -eq 'start') {
        $env:ORCH_AGENT = "claude"
        $p = "$env:USERPROFILE\orch-mobile-$([guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Directory $p -ErrorAction Stop | Out-Null
        Set-Location $p -ErrorAction Stop
        $out = O init | Out-String; L $out
        Check ($LASTEXITCODE -eq 0) "orch init in fresh workspace"
        $since = (Results "$env:USERPROFILE\.orch-tool\finish.log").Count
        $out = O addon add relay --yes | Out-String; L $out
        Check ($LASTEXITCODE -eq 0 -and (WaitFinish $out $since)) "relay add-on turned on"
        $out = O relay mobile on --hours 4 --json | Out-String; L $out
        Check ($LASTEXITCODE -eq 0 -and $out -match '"on"\s*:\s*true') "mobile mode on for four hours"
        $state = Get-Content "$p\.orch\run\mobile-mode.json" -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        $keeperPid = [int]$state.keeper_pid
        if ($keeperPid -le 0) { throw "mobile-mode.json has no keeper_pid" }
        $keeper = Get-Process -Id $keeperPid -ErrorAction SilentlyContinue
        Check ($null -ne $keeper) "keeper $keeperPid is running"
        if (-not $keeper) { throw "keeper is not running" }
        Set-Content -Path $pidFile -Value $keeperPid -ErrorAction Stop
        # Persist the workspace and process creation time so subsequent tasks do not accept a reused PID.
        @{ workspace = $p; started = $keeper.StartTime.ToUniversalTime().Ticks.ToString();
            executable = "$($keeper.ProcessName).exe" } |
            ConvertTo-Json | Set-Content -Path $contextFile -ErrorAction Stop
        L "keeper pid: $keeperPid ($pidFile); workspace: $p"
    } else {
        $keeperPid = [int](Get-Content $pidFile -Raw -ErrorAction Stop).Trim()
        if ($keeperPid -le 0) { throw "invalid saved keeper PID" }
        $context = Get-Content $contextFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        Set-Location $context.workspace -ErrorAction Stop
        $keeper = Get-Process -Id $keeperPid -ErrorAction SilentlyContinue
        if ($Phase -eq 'check') {
            $same = $null -ne $keeper -and $keeper.StartTime.ToUniversalTime().Ticks.ToString() -eq $context.started
            Check $same "keeper $keeperPid survived the starting shell/task"
            PowerRequests $true $context.executable
        } else {
            $out = O relay mobile off --json | Out-String; L $out
            Check ($LASTEXITCODE -eq 0 -and $out -match '"on"\s*:\s*false') "mobile mode off"
            $t0 = Get-Date
            while ((Get-Process -Id $keeperPid -ErrorAction SilentlyContinue) -and
                ((Get-Date) - $t0).TotalSeconds -lt 20) { Start-Sleep 1 }
            Check ($null -eq (Get-Process -Id $keeperPid -ErrorAction SilentlyContinue)) "keeper $keeperPid exited within 20 seconds"
            PowerRequests $false $context.executable
        }
    }
} catch { Check $false "mobile mode ${Phase}: $_" }
if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
