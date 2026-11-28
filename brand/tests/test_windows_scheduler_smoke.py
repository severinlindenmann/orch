"""Exercise the Windows smoke's ticket setup without installing or starting anything."""

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def test_scheduler_uses_an_isolated_test_workspace():
    script = (ROOT / "e2e/windows/scheduler-flow.ps1").read_text(encoding="utf-8")
    relative = re.search(r'\$p = "\$env:USERPROFILE\\([^"\n]+)"', script).group(1)
    assert PureWindowsPath(relative).is_relative_to(PureWindowsPath(".orch-test"))


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell is needed (available on Windows CI)")
@pytest.mark.parametrize("case", ["ok", "command-failed", "invalid-json", "missing-id", "check-failed"])
def test_scheduler_ticket_setup(tmp_path, case):
    # Load just the functions through the parser: never execute the installation/background flow.
    script = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:FLOW, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('O', 'NewSmokeTicket')) {
    $fn = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    if (-not $fn) { throw "missing $name" }
    Invoke-Expression $fn.Extent.Text
}
$log = Join-Path $env:TEST_DIR 'flow.log'
$script:checks = 0
function cmd {
    $line = $args[1]
    $global:LASTEXITCODE = 0
    if ($line -like 'orch ticket new *') {
        if ($line -like '*2>&1*' -or $line -notlike '*2>>*') { throw 'stderr mixed into JSON' }
        Add-Content $log 'a diagnostic on stderr'
        switch ($env:CASE) {
            'command-failed' { $global:LASTEXITCODE = 2; '{"error":"refused"}'; return }
            'invalid-json' { 'not JSON'; return }
            'missing-id' { '{"title":"Scheduled smoke"}'; return }
        }
        # Native programs return one pipeline string per line, not a single JSON string.
        '{', '  "id": "t_abc123",', '  "title": "Scheduled smoke"', '}'
    } elseif ($line -like 'orch check add t_abc123 *') {
        $script:checks++
        if ($env:CASE -eq 'check-failed') { $global:LASTEXITCODE = 2; 'refused'; return }
        'Added c1'
    } else { throw "unexpected command: $line" }
}
try { $id = NewSmokeTicket 'Scheduled smoke' } catch {
    if ($env:CASE -eq 'ok') { throw }
    $expected = switch ($env:CASE) {
        'command-failed' { 'ticket new failed' }
        'invalid-json' { 'JSON' }
        'missing-id' { 'returned no id' }
        'check-failed' { 'check add failed' }
    }
    if ($_.Exception.Message -notmatch $expected) { throw }
    if ($env:CASE -ne 'check-failed' -and $script:checks -ne 0) { throw 'used a missing ticket' }
    exit 0
}
if ($env:CASE -ne 'ok') { throw 'setup error was ignored' }
if ($id -ne 't_abc123' -or $script:checks -ne 1) { throw 'wrong ticket or missing checklist' }
if ((Get-Content $log -Raw) -notmatch 'a diagnostic on stderr') { throw 'diagnostic was lost' }
'''
    env = {
        **os.environ,
        "FLOW": str(ROOT / "e2e/windows/scheduler-flow.ps1"),
        "TEST_DIR": str(tmp_path),
        "CASE": case,
    }
    encoded = base64.b64encode(script.encode("utf-16le")).decode()
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ORCH-2406: on a loaded VM the automation's helper start timed out once, and the flow failed on the question
# "The helper could not start: orch could not be run (TimeoutExpired)". The flow now answers Try again once.
RETRY_CASES = {
    # case: (DoneWithin's answer, how often the flow answered Try again)
    "done": (True, 0),
    "retry-then-done": (True, 1),
    "fails-twice": (False, 1),
    "refused": (False, 1),
    "other-reason": (False, 0),
}


def test_the_flow_retries_only_the_timed_out_helper_start_and_only_once():
    script = (ROOT / "e2e/windows/scheduler-flow.ps1").read_text(encoding="utf-8")
    body = script.split("function DoneWithin($tid, $sec) {", 1)[1].split("\n}\n", 1)[0]
    assert "orch could not be run \\(TimeoutExpired\\)" in body and "-not $retried" in body
    assert body.count("O answer $tid $q '\"Try again\"' --by human:owner") == 1
    assert "$retried = $true" in body and "$t0 = Get-Date" in body.split("$retried = $true", 1)[1]
    # the limit of the helper start itself stays as it is (the ask: the wait is in the flow)
    cli = (ROOT / "workspace-addons/automation/src/orch_automation/orchcli.py").read_text(encoding="utf-8")
    assert cli.count("timeout=120") == 2


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell is needed (available on Windows CI)")
@pytest.mark.parametrize("case", sorted(RETRY_CASES))
def test_scheduler_done_within_retries_the_helper_start_once(tmp_path, case):
    script = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:FLOW, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('L', 'O', 'DoneWithin')) {
    $fn = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    if (-not $fn) { throw "missing $name" }
    Invoke-Expression $fn.Extent.Text
}
$log = Join-Path $env:TEST_DIR 'flow.log'
function Start-Sleep { [System.Threading.Thread]::Sleep(100) }
$script:answers = 0
function cmd {
    $line = $args[1]
    $global:LASTEXITCODE = 0
    $failed = "Needs an answer:`n  The helper could not start: orch could not be run (TimeoutExpired). (Try again / Leave it)  [q1]`nChecklist:"
    if ($line -like 'orch ticket show t_abc123*') {
        switch ($env:CASE) {
            'done' { 'Status: Done - 1 of 1 done' }
            'retry-then-done' { if ($script:answers) { 'Status: Done - 1 of 1 done' } else { $failed } }
            'fails-twice' { if ($script:answers) { $failed.Replace('[q1]', '[q2]') } else { $failed } }
            'refused' { $failed }
            'other-reason' { '  The helper could not start: no agent is set up here. (Try again / Leave it)  [q1]' }
        }
    } elseif ($line -like 'orch answer t_abc123 q1 "Try again" --by human:owner*') {
        $script:answers++
        if ($env:CASE -eq 'refused') { $global:LASTEXITCODE = 2; 'refused' } else { 'Answered' }
    } else { throw "unexpected command: $line" }
}
$ok = DoneWithin 't_abc123' 2
if ("$ok" -ne $env:WANT_OK) { throw "DoneWithin gave $ok, want $($env:WANT_OK)" }
if ("$($script:answers)" -ne $env:WANT_ANSWERS) { throw "answered $($script:answers) times, want $($env:WANT_ANSWERS)" }
$said = if (Test-Path $log) { Get-Content $log -Raw } else { '' }  # nothing is logged when it is done at once
if ($env:WANT_ANSWERS -eq '1' -and $said -notmatch 'one retry') { throw 'the retry is not in the log' }
if ($env:CASE -eq 'refused' -and $said -notmatch 'no retry') { throw 'the refused answer is not in the log' }
'''
    ok, answers = RETRY_CASES[case]
    env = {
        **os.environ,
        "FLOW": str(ROOT / "e2e/windows/scheduler-flow.ps1"),
        "TEST_DIR": str(tmp_path),
        "CASE": case,
        "WANT_OK": str(ok),
        "WANT_ANSWERS": str(answers),
    }
    encoded = base64.b64encode(script.encode("utf-16le")).decode()
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
