"""Workspace look (contracts/look.md): LOOK-3 relay, LOOK-4 publish. Plain HTTP; the dashboard and phone parts are LOOK-1/2/5."""
from __future__ import annotations

import os

from lib import check, http, scenario
from scenarios_pub import share, link_parts


def ws_hdr(wid: str, tok: str) -> dict:
    return {"X-Orch-Workspace": wid, "Authorization": f"Bearer {tok}"}


@scenario("LOOK-3")
def look3(e):
    """Relay: admin sets a look before the workspace connects (200), the workspace takes over, then the admin gets 409;
    the phone list carries icon and colour."""
    r = e.rel.admin.call("POST", "/admin/api/workspaces", {"name": e.label("Looky"), "description": "d", "tags": [], "icon": "code", "color": "blue"})
    check(r.status == 201, f"add: {r}")
    j = r.json()
    wid, tok = j["id"], j["token"]
    e.cleanup.append(lambda: e.rel.admin.call("DELETE", f"/admin/api/workspaces/{wid}"))
    p = e.rel.admin.call("PATCH", f"/admin/api/workspaces/{wid}", {"icon": "house"})
    check(p.status == 200, f"admin patch before connect: {p}")
    who = http("GET", e.rel.url + "/v1/whoami", ws_hdr(wid, tok)).json()
    check((who["icon"], who["color"], who["look_by"]) == ("house", "blue", "admin"), f"whoami {who}")
    # the workspace connects and sends its own look
    m = http("PATCH", e.rel.url + "/v1/me", ws_hdr(wid, tok), {"icon": "wallet", "color": "amber"})
    check(m.status == 200 and m.json()["look_by"] == "workspace", f"workspace patch: {m}")
    p = e.rel.admin.call("PATCH", f"/admin/api/workspaces/{wid}", {"name": e.label("Looky2"), "icon": "code"})
    check(p.status == 409, f"admin patch after connect should be 409: {p}")
    lst = e.rel.admin.call("GET", "/admin/api/workspaces").json()["items"]
    mine = [w for w in lst if w["id"] == wid][0]
    check(mine["icon"] == "wallet" and mine["name"] == e.label("Looky"), f"409 stored something: {mine}")
    bad = http("PATCH", e.rel.url + "/v1/me", ws_hdr(wid, tok), {"icon": "unicorn"})
    check(bad.status == 422, f"unknown icon {bad.status}")
    # phone list
    pr = e.rel.admin.call("POST", "/admin/api/phones", {"name": "Look phone", "workspaces": [wid]})
    check(pr.status == 201, f"phone: {pr}")
    code = pr.json()["link"].split("code=")[1]
    pair = http("POST", e.rel.url + "/v1/phone/pair", None, {"code": code, "name": "Look phone"})
    check(pair.status == 201, f"pair: {pair}")
    pj = pair.json()
    e.cleanup.append(lambda: e.rel.admin.call("DELETE", f"/admin/api/phones/{pj['phone_id']}"))
    items = http("GET", e.rel.url + "/v1/phone/workspaces", {"X-Orch-Phone": pj["phone_id"], "Authorization": f"Bearer {pj['token']}"}).json()["items"]
    w = [i for i in items if i["id"] == wid][0]
    check(w["icon"] == "wallet" and w["color"] == "amber", f"phone item {w}")
    return "admin 200 before, 409 after; phone has icon/colour"


@scenario("LOOK-4")
def look4(e):
    """Publish: a shared file's /f/<id>/meta has the workspace name and look; switched off -> workspace null."""
    pid, tok = e.connect_publish("Pilatus")
    r, _ = share(e, "Pilatus", name="look4.bin", size=2000)
    _, fid, _ = link_parts(r["link"])
    ok = http("PATCH", e.pub.url + "/v1/me", ws_hdr(pid, tok), {"icon": "wallet", "color": "amber"})
    check(ok.status == 200, f"look patch: {ok}")
    m = http("GET", f"{e.pub.url}/f/{fid}/meta")
    check(m.status == 200 and m.headers.get("cache-control") == "no-store", f"meta {m.status}")
    ws = m.json()["workspace"]
    check(ws and ws["icon"] == "wallet" and ws["color"] == "amber" and ws["name"], f"meta {ws}")
    off = http("PATCH", e.pub.url + "/v1/me", ws_hdr(pid, tok), {"show_on_shared_pages": False})
    check(off.status == 200, f"switch off: {off}")
    m = http("GET", f"{e.pub.url}/f/{fid}/meta")
    check(m.status == 200 and m.json() == {"workspace": None}, f"meta after off: {m.text}")
    http("PATCH", e.pub.url + "/v1/me", ws_hdr(pid, tok), {"show_on_shared_pages": True})
    return "meta on/off"


def _items(j):
    return j.get("items", j.get("workspaces", [])) if isinstance(j, dict) else j


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
    adm = next(w for w in _items(e.rel.admin.call("GET", "/admin/api/workspaces").json()) if w["id"] == wid)
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
