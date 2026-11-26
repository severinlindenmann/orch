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
