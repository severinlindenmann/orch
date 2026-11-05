"""W0 seams: moved commands behave exactly like before; hidden placeholders say not available.

The help goldens double as the proof that the placeholder groups are hidden.
"""
# ruff: noqa: E501

import pytest

from orch import cli, tickets

# Captured from develop (4b4a62c) in an empty folder; the only fields that vary by program name are normalised.
GOLDEN = {
    "--help": "usage: orch [-h] [--version] <command> ...\n\norch: tickets with evidence for any agent tool\n\npositional arguments:\n  <command>\n    init      set up this folder (safe to repeat)\n    start     start the add-ons that run in the background here\n    stop      stop them (asks which workspace when you are outside one)\n    status    what runs in the background, and where\n    addon     add-ons: add, remove, list\n    ticket    tickets\n    check     checklist\n    ask       ask a question and wait for the answer\n    needs     what waits for a person\n\noptions:\n  -h, --help  show this help message and exit\n  --version   show program's version number and exit\n\nMore commands: orch --help-all\n",
    "--help-all": "usage: orch [-h] [--version] <command> ...\n\norch: tickets with evidence for any agent tool\n\npositional arguments:\n  <command>\n    init      set up this folder (safe to repeat)\n    update    install the latest orch and the add-ons you use\n    start     start the add-ons that run in the background here\n    stop      stop them (asks which workspace when you are outside one)\n    status    what runs in the background, and where\n    addon     add-ons: add, remove, list\n    ticket    tickets\n    wait      same as: ticket wait\n    check     checklist\n    log       add a history entry\n    ask       ask a question and wait for the answer\n    answer    answer a question\n    link      links\n    ext       add-on data on a ticket\n    needs     what waits for a person\n\noptions:\n  -h, --help  show this help message and exit\n  --version   show program's version number and exit\n",
    "status": "Nothing runs in the background. Start it in a workspace: orch start\n",
    "status --json": "[]\n",
    "addon list": "  publish     off   Shares files and small apps by private link.\n  relay       off   Messages and tasks between workspaces and phones.\n",
    "addon list --json": '[\n  {\n    "name": "publish",\n    "version": "0.1.0",\n    "description": "Shares files and small apps by private link.",\n    "source": "built-in",\n    "active": false,\n    "dashboard": null,\n    "ticket_view": [],\n    "background": false,\n    "recommended": false,\n    "page": null,\n    "running": false\n  },\n  {\n    "name": "relay",\n    "version": "0.1.0",\n    "description": "Messages and tasks between workspaces and phones.",\n    "source": "built-in",\n    "active": false,\n    "dashboard": null,\n    "ticket_view": [],\n    "background": false,\n    "recommended": false,\n    "page": null,\n    "running": false\n  }\n]\n',
    "start --help": "usage: orch start [-h] [--json] [--by BY] [--no-open]\n\noptions:\n  -h, --help  show this help message and exit\n  --json      machine-readable output\n  --by BY     actor, agent:<tool> or human:<name> (default: detected)\n  --no-open   do not open the dashboard in the browser\n",
    "stop --help": "usage: orch stop [-h] [--json] [--by BY] [--all] [--pick] [PATH|NAME]\n\npositional arguments:\n  PATH|NAME   the workspace to stop\n\noptions:\n  -h, --help  show this help message and exit\n  --json      machine-readable output\n  --by BY     actor, agent:<tool> or human:<name> (default: detected)\n  --all       stop every running workspace\n  --pick      choose from the running workspaces\n",
    "addon --help": "usage: orch addon [-h] {add,remove,uninstall,list} ...\n\npositional arguments:\n  {add,remove,uninstall,list}\n    add                 install an add-on and turn it on here\n    remove              turn an add-on off in this workspace\n    uninstall           remove an add-on from this computer\n\noptions:\n  -h, --help            show this help message and exit\n",
}


@pytest.mark.parametrize("cmd", list(GOLDEN))
def test_output_is_unchanged(proj, capsys, cmd):
    try:
        code = cli.main(cmd.split())
    except SystemExit as e:  # --help exits from argparse
        code = e.code
    cap = capsys.readouterr()
    assert code == 0 and cap.out == GOLDEN[cmd] and cap.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "done"],
    ],
)
def test_placeholders_say_not_available(proj, run, argv):
    code, out, err = run(*argv)
    assert code == 2 and "not available yet" in err and out == ""


def test_provenance_unchanged(proj, monkeypatch):
    monkeypatch.delenv("ORCH_AGENT", raising=False)
    assert tickets.agent_tool() is None
    monkeypatch.setenv("CLAUDECODE", "1")
    assert tickets.current_actor() == "agent:claude"
    monkeypatch.setenv("ORCH_AGENT", "x")
    assert tickets.current_actor() == "agent:x"
