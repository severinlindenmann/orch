import sys
import types
from importlib.metadata import EntryPoint

from orch import cli


def test_unknown_command_goes_to_addon_entry_point(monkeypatch, capsys):
    seen = {}
    mod = types.ModuleType("fake_addon_mod")
    mod.main = lambda argv: seen.setdefault("argv", argv) and 0
    monkeypatch.setitem(sys.modules, "fake_addon_mod", mod)
    ep = EntryPoint("zzz", "fake_addon_mod:main", "orch.addons")
    monkeypatch.setattr(cli, "_addon_command", lambda n: ep if n == "zzz" else None)
    assert cli.main(["zzz", "serve", "--port", "1"]) == 0
    assert seen["argv"] == ["serve", "--port", "1"]


def test_addon_exit_code_is_passed_on(monkeypatch):
    mod = types.ModuleType("fake_addon_mod2")
    mod.main = lambda argv: 3
    monkeypatch.setitem(sys.modules, "fake_addon_mod2", mod)
    ep = EntryPoint("zzz", "fake_addon_mod2:main", "orch.addons")
    monkeypatch.setattr(cli, "_addon_command", lambda n: ep)
    assert cli.main(["zzz"]) == 3


def test_core_commands_win_over_addons(monkeypatch, proj):
    monkeypatch.setattr(cli, "_addon_command", lambda n: (_ for _ in ()).throw(AssertionError(n)))
    assert cli.main(["init"]) == 0


def test_unknown_without_addon_is_a_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_addon_command", lambda n: None)
    try:
        cli.main(["nonesuch"])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError


def test_real_entry_point_lookup_finds_nothing_for_unknown():
    assert cli._addon_command("definitely-not-installed") is None
