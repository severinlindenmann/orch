# Mobile mode keeper on a Windows desktop session (winvm clone): run from an elevated shell (`winvm run <clone> this.ps1`).
# The flow (mobile-mode-flow.ps1) runs as the console user through scheduled tasks that need an interactive logon
# (-LogonType Interactive = the user's desktop session), one task per phase, so the keeper has to outlive the task that
# started it. powercfg /requests (admin) is run here between the phases.
#   mobile-mode-desktop.ps1 [-User dev] [-Ref develop] [-Flow C:\Users\Public\mobile-mode-flow.ps1]
param([string]$User = "dev", [string]$Ref = "develop", [string]$Flow = "C:\Users\Public\mobile-mode-flow.ps1",
    [string]$Installer = "C:\Users\Public\install.ps1")
$ErrorActionPreference = "Stop"
$sid = (New-Object Security.Principal.NTAccount($User)).Translate([Security.Principal.SecurityIdentifier]).Value
$home_ = (Get-CimInstance Win32_UserProfile | Where-Object SID -eq $sid).LocalPath
Remove-Item "$home_\orch-flow.log" -Force -ErrorAction SilentlyContinue
function Phase($name) {
    $cmd = "`$env:Path = '$env:Path'; `$env:ORCH_REF = '$Ref'; `$env:ORCH_INSTALL_PS1 = '$Installer'; " +
        "Invoke-Expression ('& { ' + (Get-Content '$Flow' -Raw) + ' } -Phase $name')"
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
    $a = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -NonInteractive -EncodedCommand $enc"
    $p = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$User" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName "orchmm-$name" -Action $a -Principal $p -Force | Out-Null
    Start-ScheduledTask "orchmm-$name"
    $t0 = Get-Date
    do { Start-Sleep 5; $s = (Get-ScheduledTask "orchmm-$name").State } while ($s -eq "Running" -and ((Get-Date) - $t0).TotalSeconds -lt 900)
    "phase $name task state $s result $((Get-ScheduledTaskInfo "orchmm-$name").LastTaskResult)"
    Unregister-ScheduledTask "orchmm-$name" -Confirm:$false
}
whoami; query user
Phase start
"--- the starting task has ended; powercfg /requests with the keeper alive:"
powercfg /requests
Phase check
Phase off
"--- powercfg /requests after off:"
powercfg /requests
"--- flow log"
Get-Content "$home_\orch-flow.log"
$r = @(Get-Content "$home_\orch-flow.log" | Where-Object { $_ -match '^RESULT ' })
if ($r.Count -ne 3 -or ($r | Where-Object { $_ -ne "RESULT ok" })) { exit 1 }
