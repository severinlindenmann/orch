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


@scenario("LOOK-2")
def look2(e):
    """Dashboard: Settings > General picks Wallet/Amber (config + relay), edits the description (pending), switches the
    shared-pages switch off; the sidebar switcher lists both workspaces with badges. Browser half: look_dash.cjs."""
    import json
    import os
    import shutil
    from pathlib import Path

    pw = os.environ.get("PW_DIR") or next((str(p) for p in (Path.home() / "orch-dev" / "e2e" / "dashboard" / "node_modules",
                                                           Path(__file__).parent / "walkthrough" / "node_modules") if (p / "playwright").is_dir()), "")
    node = shutil.which("node", path=os.environ.get("PATH", "") + os.pathsep + e.path)
    if not pw or not node:
        from lib import Skip
        raise Skip("node + playwright not available (set PW_DIR to a node_modules folder)")
    n, other = "Pilatus", "Home"
    wid, _ = e.connect_relay(n)
    e.addon_add(e.ws(n), "dashboard")
    e.addon_add(e.ws(other), "dashboard")
    e.orch(other, "look", "set", "--icon", "house", "--color", "teal", by="human:e2e")
    urls = {}
    try:
        for w in (n, other):
            e.orch(w, "start", "--no-open")
        rows = e.orchj(n, "status")
        for r in rows:
            for a in r["addons"]:
                if a["addon"] == "dashboard":
                    urls[r["name"]] = a["url"]
        check(set(urls) >= {n, other}, f"both dashboards running: {urls}")
        shots = os.environ.get("LOOK2_SHOTS", "")
        env = {**e.env, "PW_DIR": pw}
        rc, out, err = e.sh([node, str(Path(__file__).parent / "look_dash.cjs"), urls[n], shots, "Product work, now with a Wallet"], env=env, timeout=180)
        check(rc == 0, f"browser half failed: {(err or out)[-400:]}")
        got = json.loads(out.strip().splitlines()[-1])
    finally:
        e.sh(["orch", "stop", "--all"], cwd=e.ws(n))
    check("Saved" in got["status"] and got["title"].startswith(n), f"saved: {got}")
    show = e.orchj(n, "look", "show")
    check((show["icon"], show["color"], show["set_by"]) == ("wallet", "amber", "human"), f"look show {show}")
    who = e.rapi(n, "GET", "/v1/whoami").json()
    check((who["icon"], who["color"]) == ("wallet", "amber"), f"relay whoami {who}")
    check((who.get("pending") or {}).get("description") == "Product work, now with a Wallet", f"pending {who.get('pending')}")
    check("Waiting for approval" in got["pending"], f"pending text {got['pending']!r}")
    check(got["shared"] == "false" and e.orchj(n, "look", "shared-pages")["on"] is False, f"shared-pages {got['shared']}")
    check(set(got["items"]) >= {n, other}, f"switcher items {got['items']}")
    check(["teal", True] in got["itemLooks"] and ["amber", True] in got["itemLooks"], f"badges {got['itemLooks']}")
    check(got["noOverflow"] and not got["errors1280"] and not got["errors720"], f"layout/errors {got}")
