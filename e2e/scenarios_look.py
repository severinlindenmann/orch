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
