"""Fixture workspace + fake-orch-backed Insights server for e2e/focus_insights_shots.cjs.

    python e2e/focus_insights/insights_server.py <dir> <port>

A throw-away workspace in <dir> and a fake `orch` that answers the three reads Insights makes
(`record counts`, `record settings`, `ticket list --all`) from contracts/examples/counts/valid-answer.json plus a few
extra items (a skill that fails, a key nobody used). Run it from the insights add-on's environment
(`uv run --project workspace-addons/insights`). Writes only under <dir> (under ~/.orch-test). Prints `ready`.
The fake has no person session: widening is shown watch-only, exactly like an Insights page opened without the dashboard.
"""

import copy
import json
import sys
from pathlib import Path

D, PORT = Path(sys.argv[1]).resolve(), int(sys.argv[2])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace-addons" / "insights" / "src"))
sys.path.insert(0, str(ROOT / "workspace" / "src"))
from orch_insights.server import make_server  # noqa: E402

ws = D / "Pilatus"
(ws / ".orch").mkdir(parents=True, exist_ok=True)
answer = json.loads((ROOT / "contracts/examples/counts/valid-answer.json").read_text())
base = answer["items"][0]


def item(kind, name, source, uses, ok, failed, refused, used, seen="yes", **kw):
    it = copy.deepcopy(base)
    it.update(kind=kind, name=name, source=source, uses=uses, ok=ok, failed=failed, refused=refused, seen=seen, **kw)
    it["runs"] = {"used": used, "of": 23, "unseen": 4}
    return it


answer["items"] += [
    item("skill", "weekly-summary", "admin", 5, 2, 3, 0, 4, tickets={"done": 1, "sent_back": 2, "open": 1}),
    item("skill", "event-planning", "workspace", 9, 9, 0, 0, 6, first_seen="2026-11-14T08:00:00Z"),
    item("key", "old-slack-token", "workspace", 0, 0, 0, 0, 0, seen="not_seen", first_seen=None, last_seen=None, versions=[]),
]
answer["inventory"]["keys"].append({"name": "old-slack-token", "type": "token", "source": "workspace"})
answer["inventory"]["skills"].append({"name": "weekly-summary", "source": "admin", "version": "sha256:" + "d" * 64, "shadowed": False})
settings = {"keep_days": 90, "max_mb": 2048, "share_counts": True, "share_names": False, "record_mb": 312, "detail_mb": 280, "runs": 27}
tickets = [{"id": "t_pil1aaaa", "title": "Plan the offsite agenda"}, {"id": "t_pil2bbbb", "title": "Write the newsletter"}]
fake = D / "orch"
fake.write_text(
    f"#!{sys.executable}\nimport sys\na = sys.argv[1:]\n"
    f"if a[:2] == ['record', 'counts']: print({json.dumps(answer)!r})\n"
    f"elif a[:2] == ['record', 'settings']: print({json.dumps(settings)!r})\n"
    f"elif a[:2] == ['ticket', 'list']: print({json.dumps(tickets)!r})\n"
    "else: sys.exit(2)\n"
)
fake.chmod(0o755)
srv = make_server(ws, PORT, orch_bin=str(fake))
print("ready", flush=True)
srv.serve_forever()
