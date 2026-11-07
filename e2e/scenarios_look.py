"""Workspace look (icon + colour) scenarios. LOOK-1 is the core + CLI side: it needs the relay look support (L3)."""
from __future__ import annotations

from lib import check, scenario


@scenario("LOOK-1")
def look1(e):
    """orch look list = 100 icons / 12 colours; an agent sets the look and the relay shows it (look_by workspace);
    a person's pick then locks out the agent."""
    n = "Pilatus"
    wid, _ = e.connect_relay(n)
    lst = e.orchj(n, "look", "list")
    check(len(lst["icons"]) == 100 and len(lst["colors"]) == 12, f"list {len(lst['icons'])}/{len(lst['colors'])}")
    show = e.orchj(n, "look", "show")
    check(show["set_by"] is None and show["icon"] is None, f"fresh workspace {show}")

    e.orch(n, "look", "set", "--icon", "wallet", "--color", "amber", by="agent:claude")
    who = e.rapi(n, "GET", "/v1/whoami").json()
    check((who["icon"], who["color"], who["look_by"]) == ("wallet", "amber", "workspace"), f"whoami {who}")
    adm = next(w for w in e.rel.admin.call("GET", "/admin/api/workspaces").json() if w["id"] == wid)
    check((adm["icon"], adm["color"], adm["look_by"]) == ("wallet", "amber", "workspace"), f"admin {adm}")
    r = e.rel.admin.call("PATCH", f"/admin/api/workspaces/{wid}", {"icon": "code"})
    check(r.status == 409, f"admin change after the workspace chose: {r}")

    e.orch(n, "look", "set", "--icon", "bank", "--color", "teal", by="human:e2e")
    rc, _, err = e.orch(n, "look", "set", "--icon", "house", by="agent:claude", ok=False)
    check(rc == 2 and "person chose" in err, f"agent after person: {rc} {err!r}")
    who = e.rapi(n, "GET", "/v1/whoami").json()
    check((who["icon"], who["color"]) == ("bank", "teal"), f"whoami after person pick {who}")
    st = e.orchj(n, "status")
    check(isinstance(st, list), "status --json")
