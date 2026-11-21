"""Fixture workspace + the real dashboard server (standalone, files only) for e2e/focus_insights_shots.cjs.

    python e2e/focus_insights/dashboard_server.py <dir> <port>

A throw-away workspace in <dir> with one ticket (and the files of the demo ticket of every result widget kind),
served by orch_dashboard.server.make_server with no orch command
(it reads the files only), so the page, its kit and the style guide come from this checkout. Run it from the dashboard
add-on's environment (`uv run --project workspace-addons/dashboard`). Writes only under <dir> (under ~/.orch-test).
Prints `ready`.
"""

import json
import sys
from pathlib import Path

D, PORT = Path(sys.argv[1]).resolve(), int(sys.argv[2])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace-addons" / "dashboard" / "src"))
sys.path.insert(0, str(ROOT / "workspace" / "src"))
from orch_dashboard.server import Handler, make_server  # noqa: E402

# A fixture server with no page session (nobody could sign in): the test browser counts as signed in to READ.
# The real servers need the sign-in for every data read (ORCH-481); this fixture only listens on 127.0.0.1.
Handler._signed_in = lambda self: True

ws = D / "Pilatus"
(ws / ".orch" / "tickets").mkdir(parents=True, exist_ok=True)
ticket = json.loads((ROOT / "contracts" / "review" / "ticket.example.json").read_text())
(ws / ".orch" / "tickets" / f"{ticket['id']}.json").write_text(json.dumps(ticket))
# ORCH-697: the files of the demo ticket with every result widget kind (e2e/focus_d/widgets_ticket.json)
demo = json.loads((ROOT / "e2e" / "focus_d" / "widgets_ticket.json").read_text())
dt = demo["ticket"]
# only its files: the ticket itself joins the page's state in the steps that use it (e2e/focus_d/steps.cjs)
art = ws / ".orch" / "tickets" / dt["id"] / "artifacts"
art.mkdir(parents=True, exist_ok=True)
samples = ROOT / "workspace" / "src" / "orch_ui" / "static" / "samples"
for name, f in demo["files"].items():
    if "sample" in f:
        (art / name).write_bytes((samples / f["sample"]).read_bytes())
    else:
        (art / name).write_text(f["text"])

srv = make_server(ws, PORT)
print("ready", flush=True)
srv.serve_forever()
