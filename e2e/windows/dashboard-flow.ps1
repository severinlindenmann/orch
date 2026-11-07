# The dashboard as a standard Windows user sees it: install orch if a flow before did not, a workspace with one ticket,
# the dashboard add-on, orch start, then dashboard-smoke.mjs with Playwright inside this machine (nothing is forwarded
# out of the VM). Screenshots go to %USERPROFILE%\orch-shots. Last log line "RESULT ok" or "RESULT fail: <what>".
# Started by run-as-standard-user.ps1 (-Flows dashboard or standard-user,dashboard), never by hand.
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
$fails = @()
function L($m) { Add-Content -Path $log -Value $m }
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
L ""; L "=== dashboard (Playwright inside the machine)"
$pub = Split-Path $env:ORCH_INSTALL_PS1
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
if (-not (Get-Command orch -ErrorAction SilentlyContinue)) {
    L "--- install"
    try { Get-Content $env:ORCH_INSTALL_PS1 -Raw | Invoke-Expression *>&1 | Out-String | % { L $_ } } catch { L "install threw: $_" }
}
Check ("$(cmd /c 'orch --version < NUL 2>&1')" -match "^orch ") "orch runs"
function O { cmd /c "orch $($args -join ' ') < NUL 2>&1" }
function WaitFinish($out) {  # add-on installs finish in the background on Windows (see standard-user-flow.ps1)
    $m = [regex]::Match("$out", 'Log: (\S+)')
    if (-not $m.Success) { return $true }
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 600) {
        $last = Get-Content $m.Groups[1].Value -ErrorAction SilentlyContinue | Select-String '^\S+ \S+ RESULT ' | Select -Last 1
        if ($last) { L "finisher: $last"; return ("$last" -match 'RESULT ok') }
        Start-Sleep 3
    }
    $false
}

$title = "Windows dashboard smoke"
$p = "$env:USERPROFILE\orch-dash"; New-Item -ItemType Directory -Force $p | Out-Null; Set-Location $p
O init | Out-String | % { L $_ }
O ticket new "`"$title`"" | Out-String | % { L $_ }
Check ($LASTEXITCODE -eq 0) "a ticket for the dashboard"
if (-not ("$(O addon list)" -match "dashboard")) {
    $out = O addon add dashboard --yes | Out-String; L $out
    Check (WaitFinish $out) "dashboard add-on installed"
}
$out = O start --no-open --json | Out-String; L $out
$url = [regex]::Match($out, 'http://127\.0\.0\.1:\d+').Value
Check ([bool]$url) "orch start runs the dashboard"

# Node and Playwright for this user only (no admin, nothing on the machine PATH). Chromium is an x64 build: it runs
# under emulation on ARM64 Windows.
$nodeArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
$nodeVer = "v22.11.0"
$nodeDir = "$env:LOCALAPPDATA\orch-smoke\node-$nodeVer-win-$nodeArch"
if (-not (Test-Path "$nodeDir\node.exe")) {
    New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\orch-smoke" | Out-Null
    $zip = "$env:LOCALAPPDATA\orch-smoke\node.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest "https://nodejs.org/dist/$nodeVer/node-$nodeVer-win-$nodeArch.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip "$env:LOCALAPPDATA\orch-smoke" -Force
}
$env:Path = "$nodeDir;$env:Path"
$pw = "$env:LOCALAPPDATA\orch-smoke\pw"; New-Item -ItemType Directory -Force $pw | Out-Null
Copy-Item "$pub\dashboard-smoke.mjs" $pw -Force
'{"name":"orch-win-smoke","private":true,"type":"module","dependencies":{"playwright":"1.55.0"}}' | Set-Content "$pw\package.json" -Encoding ASCII
Set-Location $pw
L (cmd /c "npm install --no-audit --no-fund --loglevel=error < NUL 2>&1" | Out-String)
L (cmd /c "npx playwright install chromium < NUL 2>&1" | Out-String)
Check (Test-Path "$pw\node_modules\playwright") "Playwright installed for this user"

$shots = "$env:USERPROFILE\orch-shots"
if ($url) {
    $smoke = cmd /c "node dashboard-smoke.mjs $url `"$shots`" `"$title`" < NUL 2>&1" | Out-String
    $code = $LASTEXITCODE
    L $smoke
    Check ($code -eq 0) "dashboard smoke: every page step passed"
}
Set-Location $p
L (O stop | Out-String)
if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
