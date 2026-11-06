# Run standard-user-flow.ps1 as a new standard (non-admin) local user, with git hidden and the execution policy at
# Windows' default (Restricted). Needs an admin shell on a THROWAWAY machine (CI runner, winvm clone): it creates a
# user, grants it "log on as a batch job" and sets the machine policy.
#   run-as-standard-user.ps1 -Ref <branch|sha> [-Installer <path to install.ps1>]
param([Parameter(Mandatory)] [string]$Ref, [string]$Installer = "$PSScriptRoot\..\..\install.ps1", [int]$MaxSec = 1500)
$ErrorActionPreference = "Stop"
$user = "orchsmoke"; $pass = "Smoke-$([guid]::NewGuid().ToString('N').Substring(0, 12))!"
$pw = ConvertTo-SecureString $pass -AsPlainText -Force
if (Get-LocalUser $user -ErrorAction SilentlyContinue) { Set-LocalUser $user -Password $pw } else {
    New-LocalUser $user -Password $pw -PasswordNeverExpires | Out-Null
    Add-LocalGroupMember Users $user
}
# A scheduled task is the way to start a process as another user from a non-interactive admin shell
# (Start-Process -Credential fails with 0xC0000142 there); it needs the batch logon right, which is not admin.
$sid = (Get-LocalUser $user).SID.Value
$tmp = New-Item -ItemType Directory -Force "$env:TEMP\orchsmoke-sec"
secedit /export /cfg "$tmp\sec.inf" /areas USER_RIGHTS | Out-Null
$inf = Get-Content "$tmp\sec.inf"
if (-not ($inf -match "SeBatchLogonRight.*$sid")) {
    if ($inf -match "^SeBatchLogonRight") { $inf = $inf -replace '^(SeBatchLogonRight = .*)$', "`$1,*$sid" }
    else { $inf = $inf -replace '^\[Privilege Rights\]$', "[Privilege Rights]`r`nSeBatchLogonRight = *$sid" }
    $inf | Set-Content "$tmp\sec2.inf" -Encoding Unicode
    secedit /configure /db "$tmp\sec.sdb" /cfg "$tmp\sec2.inf" /areas USER_RIGHTS | Out-Null
}
# Windows' default. The admin shell's own -ExecutionPolicy Bypass makes this warn ("overridden"): not an error here.
try { Set-ExecutionPolicy Restricted -Scope LocalMachine -Force } catch { }
$pub = "C:\Users\Public\orchsmoke"; New-Item -ItemType Directory -Force $pub | Out-Null
Copy-Item "$PSScriptRoot\standard-user-flow.ps1", $Installer $pub -Force
$installerName = Split-Path $Installer -Leaf
# No git for the user: PATH without any folder that holds git.exe
$path = ([Environment]::GetEnvironmentVariable("Path", "Machine") -split ";" |
    Where-Object { $_ -and -not (Test-Path (Join-Path $_ "git.exe")) }) -join ";"
# Passed as a command, not -File: a .ps1 file would itself be refused under Restricted (irm | iex is not).
$cmd = "`$env:Path = '$path'; `$env:ORCH_REF = '$Ref'; `$env:ORCH_INSTALL_PS1 = '$pub\$installerName'; " +
    "Invoke-Expression (Get-Content '$pub\standard-user-flow.ps1' -Raw)"
$enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
$a = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -NonInteractive -EncodedCommand $enc"
Register-ScheduledTask -TaskName orchsmoke -Action $a -User $user -Password $pass -RunLevel Limited -Force | Out-Null
Start-ScheduledTask orchsmoke
$t0 = Get-Date
do {
    Start-Sleep 5
    $s = (Get-ScheduledTask orchsmoke).State; $r = (Get-ScheduledTaskInfo orchsmoke).LastTaskResult
} while (($s -eq "Running" -or $r -eq 267011) -and ((Get-Date) - $t0).TotalSeconds -lt $MaxSec)
Unregister-ScheduledTask orchsmoke -Confirm:$false
$logFile = "C:\Users\$user\orch-flow.log"
if (-not (Test-Path $logFile)) { throw "the flow wrote no log (task state $s, result $r)" }
Get-Content $logFile
if (-not ((Get-Content $logFile)[-1] -eq "RESULT ok")) { exit 1 }
