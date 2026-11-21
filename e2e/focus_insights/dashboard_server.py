"""Fixture workspace + the real dashboard server (standalone, files only) for e2e/focus_insights_shots.cjs.

    python e2e/focus_insights/dashboard_server.py <dir> <port>

A throw-away workspace in <dir> with one ticket, served by orch_dashboard.server.make_server with no orch command
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

srv = make_server(ws, PORT)
print("ready", flush=True)
srv.serve_forever()
