# A relay round trip as a standard Windows user: connect a workspace to the relay, send the Mac workspace (Pilatus,
# running relay-peer.py) a text and a small file, and wait for its answer: "pong <nonce>" and the file back, same bytes.
# Needs E2E_RELAY_URL, E2E_RELAY_WS, E2E_RELAY_TOKEN, E2E_RELAY_PEER (run-as-standard-user.ps1 -EnvFile; relay-pair.py
# writes that file). Installs orch if a flow before did not. Last log line "RESULT ok" or "RESULT fail: <what>".
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
$fails = @()
function L($m) { Add-Content -Path $log -Value $m }
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
L ""; L "=== relay (round trip with the Mac workspace)"
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
if (-not (Get-Command orch -ErrorAction SilentlyContinue)) {
    L "--- install"
    try { Get-Content $env:ORCH_INSTALL_PS1 -Raw | Invoke-Expression *>&1 | Out-String | % { L $_ } } catch { L "install threw: $_" }
}
function O { cmd /c "orch $($args -join ' ') < NUL 2>&1" }
function Results($log) { @(Get-Content $log -ErrorAction SilentlyContinue | Select-String '^\S+ \S+ RESULT ') }
function WaitFinish($out, $since) {  # add-on installs finish in the background on Windows (see standard-user-flow.ps1)
    $m = [regex]::Match("$out", 'Log: (\S+)')
    if (-not $m.Success) { return $true }
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 600) {
        $last = Results $m.Groups[1].Value | Select -Skip $since | Select -Last 1  # only RESULT lines of this install
        if ($last) { L "finisher: $last"; return ("$last" -match 'RESULT ok') }
        Start-Sleep 3
    }
    $false
}
$need = "E2E_RELAY_URL", "E2E_RELAY_WS", "E2E_RELAY_TOKEN", "E2E_RELAY_PEER"
$missing = @($need | Where-Object { -not [Environment]::GetEnvironmentVariable($_) })
Check (-not $missing) "relay settings given ($($need -join ', '))"
$peer = $env:E2E_RELAY_PEER

$env:ORCH_AGENT = "claude"  # as standard-user-flow.ps1: init links .claude\skills (no agent is installed here)
$p = "$env:USERPROFILE\orch-relay"; New-Item -ItemType Directory -Force $p | Out-Null; Set-Location $p
O init | Out-String | % { L $_ }
# Always add: "addon list" also names add-ons that ship with orch but are off in this workspace (relay is one).
$since = (Results "$env:USERPROFILE\.orch-tool\finish.log").Count  # the finish log is shared with earlier flows
$out = O addon add relay --yes | Out-String; L $out
Check ($LASTEXITCODE -eq 0 -and (WaitFinish $out $since)) "relay add-on turned on"
# The token goes on the command line of a throwaway test user only; it is not written to the log.
$out = O relay connect $env:E2E_RELAY_URL --workspace $env:E2E_RELAY_WS --token $env:E2E_RELAY_TOKEN | Out-String
L ($out.Replace($env:E2E_RELAY_TOKEN, "<token>"))
Check ($LASTEXITCODE -eq 0) "orch relay connect"
L (O relay whoami | Out-String)
Check ($LASTEXITCODE -eq 0) "orch relay whoami reaches the relay"

$nonce = [guid]::NewGuid().ToString("N").Substring(0, 8)
$out = O relay send $peer "`"windows ping $nonce`"" | Out-String; L $out
Check ($LASTEXITCODE -eq 0) "send a text to the Mac workspace"
$name = "win-$nonce.txt"
$content = "file from windows $nonce`r`numlaut: $([char]0xE4)$([char]0xF6)$([char]0xFC)"
[IO.File]::WriteAllText("$p\$name", $content, (New-Object Text.UTF8Encoding $false))
$sentHash = (Get-FileHash "$p\$name").Hash
$out = O relay send $peer --file $name | Out-String; L $out
Check ($LASTEXITCODE -eq 0) "send a small file to the Mac workspace"

# Wait for the answer: the text "pong <nonce>" and the file back (same bytes), both from the peer.
$gotText = $false; $gotFile = $false; $t0 = Get-Date
while (-not ($gotText -and $gotFile) -and ((Get-Date) - $t0).TotalSeconds -lt 300) {
    O relay inbox --wait 20 | Out-Null
    foreach ($f in Get-ChildItem "$p\.orch\inbox\m_*.json" -ErrorAction SilentlyContinue) {
        $m = Get-Content $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($m.from -ne $peer) { continue }
        if (-not $gotText -and $m.type -eq "text" -and $m.body.text -match "pong $nonce") {
            $gotText = $true; L "answer: $($m.body.text) (after $([int]((Get-Date) - $t0).TotalSeconds) s)"
        }
        if (-not $gotFile -and $m.type -eq "file" -and $m.body.name -eq $name) {
            $out = O relay download $m.id | Out-String; L $out
            $saved = [regex]::Match($out, 'Saved (.+)').Groups[1].Value.Trim()
            $gotFile = $saved -and (Test-Path $saved) -and ((Get-FileHash $saved).Hash -eq $sentHash)
            L "file back: $saved (after $([int]((Get-Date) - $t0).TotalSeconds) s)"
        }
    }
}
Check $gotText "the Mac workspace answered the text"
Check $gotFile "the file came back with the same bytes"
if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
