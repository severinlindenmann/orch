"""orch Companion's workspace menu (ORCH-1722, draft C): what it shows for each answer of
`orch workspace companion list`, that it never offers a stop, that it opens only links to this computer, and how it
runs orch (no shell, a small environment, a time limit for the list). Through `--print-workspace-menu`."""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SWIFT_DIR = Path(__file__).resolve().parents[3] / "companion" / "mac"

MAC = pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc"
)
A, B, C, D = ("a" * 32, "b" * 32, "c" * 32, "d" * 32)
LIST = {
    "v": 1,
    "ok": True,
    "workspaces": [
        {
            "id": A,
            "name": "ORCH Development",
            "path": "/x",
            "state": "running",
            "dashboard_url": "http://127.0.0.1:63965",
            "start_with_mac": True,
            "protected_folder": False,
        },
        {
            "id": B,
            "name": "Fernscout",
            "path": "/y",
            "state": "running",
            "dashboard_url": "http://evil.example:80",
            "start_with_mac": False,
            "protected_folder": False,
        },
        {
            "id": C,
            "name": "Marketing",
            "path": "/z",
            "state": "stopped",
            "dashboard_url": None,
            "start_with_mac": True,
            "protected_folder": True,
        },
        {
            "id": D,
            "name": "Sales pipeline",
            "path": "/w",
            "state": "partly",
            "dashboard_url": None,
            "start_with_mac": False,
            "protected_folder": False,
        },
    ],
}


@pytest.fixture(scope="module")
def exe(tmp_path_factory):
    out = tmp_path_factory.mktemp("companion-build")
    subprocess.run([str(SWIFT_DIR / "build.sh"), str(out)], check=True, capture_output=True, timeout=600)
    return out / "orch Companion.app" / "Contents" / "MacOS" / "orch-companion"


def menu(exe, *args, env=None, timeout=60):
    r = subprocess.run(
        [str(exe), "--print-workspace-menu", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        env=env,
    )
    return [line.split("|") for line in r.stdout.splitlines()]


def listing(tmp_path, data=LIST):
    p = tmp_path / "list.json"
    p.write_text(json.dumps(data))
    return str(p)


@MAC
def test_draft_c_groups_one_click_actions_and_switches(exe, tmp_path):
    rows = menu(exe, listing(tmp_path))
    flat = ["|".join(r) for r in rows]
    assert "label|2 of 4 workspaces running|disabled" in flat
    assert [r[1] for r in rows if r[0] == "header"] == ["Running", "Partly running", "Stopped"]
    assert f"action|ORCH Development|Open dashboard|open:{A}" in flat
    assert "action|Fernscout|disabled" in flat  # a link to another computer is never opened
    assert f"action|Sales pipeline|Start the rest|start:{D}" in flat
    assert f"action|Marketing|Start now|start:{C}" in flat
    assert "submenuStart|Start with my Mac|2 on" in flat
    assert f"action|Marketing|switch:{C}|checked" in flat
    assert f"action|How to fix…|fix:{C}" in flat
    acts = [r for r in rows if r[0] == "action"]
    assert not any(r[1].lower().startswith("stop") or any(x.startswith("stop") for x in r[2:]) for r in acts)


@MAC
def test_starting_login_item_off_and_result_line(exe, tmp_path):
    flat = [
        "|".join(r) for r in menu(exe, listing(tmp_path), f"starting:{C}", "login-off", "result:Started 1")
    ]
    assert "label|Started 1|disabled" in flat
    assert "action|Marketing|Starting…|disabled" in flat
    assert "submenuStart|Start with my Mac|Off" in flat
    assert "action|Start orch Companion with my Mac|login-on" in flat
    assert f"action|ORCH Development|switch:{A}|checked|disabled" in flat


@MAC
def test_orch_missing_too_old_and_not_answering(exe, tmp_path):
    assert ["warning", "orch is not installed on this Mac", "disabled"] in menu(exe, "missing")
    assert ["action", "Update orch…", "update"] in menu(exe, "too-old")
    rows = menu(exe, listing(tmp_path), "no-answer")
    flat = ["|".join(r) for r in rows]
    assert "warning|Couldn't reach your workspaces|disabled" in flat and "action|Try again|retry" in flat
    assert all(
        r[-1] == "disabled" for r in rows if r[0] == "action" and r[1] != "Try again"
    )  # last list dimmed
    assert not any(r[1] == "Start with my Mac" for r in rows)


@MAC
def test_more_than_ten_go_under_more(exe, tmp_path):
    many = {
        "v": 1,
        "ok": True,
        "workspaces": [
            {
                "id": f"{i:032x}",
                "name": f"W{i:02}",
                "path": "/p",
                "state": "stopped",
                "dashboard_url": None,
                "start_with_mac": False,
                "protected_folder": False,
            }
            for i in range(12)
        ],
    }
    rows = menu(exe, listing(tmp_path, many))
    top = rows[: next(i for i, r in enumerate(rows) if r[0] == "submenuStart")]
    assert sum(r[0] == "action" for r in top) == 10
    assert ["submenuStart", "More…", "2"] in rows


def _fake_orch(tmp_path, body):
    p = tmp_path / "orch"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@MAC
def test_live_call_gets_a_small_environment_and_no_shell(exe, tmp_path):
    seen = tmp_path / "seen.txt"
    orch = _fake_orch(tmp_path, f'env > "{seen}"\necho "$@" >> "{seen}"\necho \'{json.dumps(LIST)}\'\n')
    env = {**os.environ, "ORCH_COMPANION_ORCH": str(orch), "SECRET_TOKEN": "canary-123", "ORCH_ROOT": "/nope"}
    flat = ["|".join(r) for r in menu(exe, "live", env=env)]
    assert "label|2 of 4 workspaces running|disabled" in flat
    got = seen.read_text()
    assert "canary-123" not in got and "ORCH_ROOT" not in got
    assert "workspace companion list" in got
    assert f"PATH={tmp_path}:" in got  # orch's own folder first on PATH


@MAC
def test_live_old_orch_and_a_hanging_orch(exe, tmp_path):
    old = _fake_orch(
        tmp_path, "echo \"orch: error: argument cmd: invalid choice: 'workspace'\" >&2\nexit 2\n"
    )
    assert ["warning", "orch is too old for this list", "disabled"] in menu(
        exe, "live", env={**os.environ, "ORCH_COMPANION_ORCH": str(old)}
    )
    hang = _fake_orch(tmp_path, "sleep 30\n")
    rows = menu(exe, "live", env={**os.environ, "ORCH_COMPANION_ORCH": str(hang)}, timeout=25)
    assert ["warning", "Couldn't reach your workspaces", "disabled"] in rows  # the 10 s limit, not a hang


@MAC
def test_a_child_holding_the_output_open_does_not_hang_the_list(exe, tmp_path):
    held = _fake_orch(tmp_path, "sleep 40 &\necho '" + json.dumps(LIST) + "'\nexit 0\n")
    rows = menu(exe, "live", env={**os.environ, "ORCH_COMPANION_ORCH": str(held)}, timeout=25)
    assert [
        "label",
        "2 of 4 workspaces running",
        "disabled",
    ] in rows  # orch's answer, not a wait for the child


@MAC
def test_a_refusal_is_not_taken_for_an_old_orch(exe, tmp_path):
    refused = _fake_orch(tmp_path, "echo 'Refused: ORCH_HOME is not a trusted folder' >&2\nexit 2\n")
    rows = menu(exe, "live", env={**os.environ, "ORCH_COMPANION_ORCH": str(refused)})
    assert ["warning", "Couldn't reach your workspaces", "disabled"] in rows
    assert not any("Refused" in "|".join(r) for r in rows)  # orch's raw text is never shown
