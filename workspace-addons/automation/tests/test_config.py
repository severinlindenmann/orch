"""The add-on reads .orch/config.toml as UTF-8 on every computer; a file it cannot read gives the defaults, never a
crash of the scheduler or the dashboard view (Windows Notepad still saves "ANSI" files)."""

from orch_automation import plain
from orch_automation.runner import load_config

DEFAULTS = {"interval": 60, "inbox_every": 60, "reports_every": 120, "report_tickets": False}


def _cfg(ws, data: bytes):
    (ws / ".orch" / "config.toml").write_bytes(data)


def test_umlauts_in_utf8_are_read_on_any_computer(ws):
    text = (
        '# Jürg Müller\n[workspace]\ntz = "Europe/Zurich"\nname = "Bücher Ölzweig"\n'
        "[automation]\ninterval = 5\n[diag]\nreport_tickets = true\n"
    )
    _cfg(ws, text.encode("utf-8"))
    cfg = load_config(ws)
    assert cfg["interval"] == 5 and cfg["report_tickets"] is True
    assert plain.workspace_tz(ws) == "Europe/Zurich"


def test_a_file_saved_in_another_encoding_gives_the_defaults(ws):
    _cfg(ws, '# Jürg\n[automation]\ninterval = 5\n[workspace]\ntz = "Europe/Zurich"\n'.encode("latin-1"))
    assert load_config(ws) == DEFAULTS
    assert plain.workspace_tz(ws) is None
    assert plain.new_repeat_zone(ws)  # falls back to this computer's zone


def test_missing_broken_or_odd_values_give_the_defaults(ws):
    assert load_config(ws) == DEFAULTS  # no file
    _cfg(ws, b"not toml [[[")
    assert load_config(ws) == DEFAULTS
    _cfg(ws, b'automation = "x"\ndiag = 1\n')
    assert load_config(ws) == DEFAULTS
    _cfg(ws, b'[automation]\ninterval = 0\ninbox_every = "soon"\nreports_every = -5\n')
    assert load_config(ws) == {**DEFAULTS, "interval": 1, "reports_every": 1}
