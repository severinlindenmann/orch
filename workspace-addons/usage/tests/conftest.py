import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper), and the core (orch) is found by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)


def switcher_data(active=1, first=(97.0, 80.0), second=(0.0, 78.0), third=(23.0, 44.0)):
    """What `cswap list --json` answers, with made-up addresses (never real ones)."""

    def acct(n, addr, org, is_org, h, w):
        return {
            "number": n,
            "email": addr,
            "organizationName": org,
            "organizationUuid": f"0000000{n}-0000-0000-0000-000000000000",
            "isOrganization": is_org,
            "active": n == active,
            "usageStatus": "ok",
            "usage": {
                "fiveHour": {"pct": h, "resetsAt": "2026-11-16T19:29:59.99+00:00"},
                "sevenDay": {"pct": w, "resetsAt": "2026-11-18T19:59:59.99+00:00", "willLastToReset": False},
            },
            "threshold": 99.9,
            "loginExpiresAt": "2026-11-17T21:03:10Z",
            "usageFetchedAt": "2026-11-16T18:06:47Z",
        }

    return {
        "schemaVersion": 1,
        "activeAccountNumber": active,
        "accounts": [
            acct(1, "first@example.test", "first@example.test's Organization", True, *first),
            acct(2, "second@example.test", "second@example.test's Organization", True, *second),
            acct(3, "third@example.test", "TEAMCO", True, *third),
        ],
    }


@pytest.fixture
def fake_switcher(tmp_path, monkeypatch):
    """A fake `cswap`: answers `list --json` from a file and refuses everything else (no switch in a test)."""
    if os.name == "nt":
        pytest.skip("shell script stub")
    d = tmp_path / "bin"
    d.mkdir()
    answer = tmp_path / "switcher.json"
    calls = tmp_path / "switcher-calls.txt"
    answer.write_text(json.dumps(switcher_data()), encoding="utf-8")
    exe = d / "cswap"
    exe.write_text(
        textwrap.dedent(f"""\
            #!{sys.executable}
            import sys
            open({str(calls)!r}, "a").write(" ".join(sys.argv[1:]) + "\\n")
            if sys.argv[1:] == ["list", "--json"]:
                sys.stdout.write(open({str(answer)!r}).read())
                sys.exit(0)
            sys.exit(3)
            """),
        encoding="utf-8",
    )
    exe.chmod(0o755)
    monkeypatch.setenv("ORCH_USAGE_SWITCHER", str(exe))

    class Fake:
        path = exe

        @staticmethod
        def answer(data):
            answer.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")

        @staticmethod
        def calls():
            return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []

    return Fake


@pytest.fixture
def no_switcher(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_USAGE_SWITCHER", str(tmp_path / "missing-cswap"))


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    monkeypatch.setenv("ORCH_ROOT", str(root))
    for k in ("ORCH_RUN", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    return root


@pytest.fixture
def cli(ws, capsys):
    from orch_usage.cli import main

    def run(*argv):
        code = main([*argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def jrun(cli, *argv):
    code, out, _ = cli(*argv, "--json")
    return code, json.loads(out)
