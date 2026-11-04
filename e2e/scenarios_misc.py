"""Mobile (M, API part only), whole flow (F1-lite) and stubs for agent/browser/phone-UI scenarios."""
from __future__ import annotations

import json
import os
import time

from lib import Fail, Skip, check, http, scenario
from scenarios_ws import EVID, tload
from scenarios_pub import link_parts, opf1_decrypt


def pair(e, names: list[str], label="Test iPhone"):
    ids = e.relay_all() if "Fresh" not in names else {**e.relay_all(), "Fresh": e.connect_relay("Fresh")[0]}
    r = e.rel.admin.call("POST", "/admin/api/phones", {"name": label, "workspaces": [ids[n] for n in names]})
    check(r.status == 201, f"add phone: {r}")
    j = r.json()
    check("orch://pair" in j["link"] and "code=pc_" in j["link"], f"pair link {j['link']}")
    code = j["link"].split("code=")[1]
    p = http("POST", e.rel.url + "/v1/phone/pair", None, {"code": code, "name": label})
    check(p.status == 201, f"pair: {p}")
    pj = p.json()
    e.cleanup.append(lambda i=pj["phone_id"]: e.rel.admin.call("DELETE", f"/admin/api/phones/{i}"))
    again = http("POST", e.rel.url + "/v1/phone/pair", None, {"code": code, "name": label})
    check(again.status in (401, 403, 404, 409, 410), f"pair code is reusable: {again.status}")
    return ids, (pj["phone_id"], pj["token"])


def phone(e, ph, method, path, body=None):
    return http(method, e.rel.url + path, {"X-Orch-Phone": ph[0], "Authorization": f"Bearer {ph[1]}"}, body)


@scenario("M1")
def m1(e):
    """Phone for Pilatus + Home: lists both with description, not Reports (API part)."""
    ids, ph = pair(e, ["Pilatus", "Home"])
    ws = phone(e, ph, "GET", "/v1/phone/workspaces").json()["items"]
    got = {w["id"]: w for w in ws}
    check(set(got) == {ids["Pilatus"], ids["Home"]}, f"phone sees {sorted(got)}")
    check(all(w["description"] for w in got.values()), "description missing")
    return "QR / orch:// opened in the Simulator: mobile lane"


@scenario("M2")
def m2(e):
    """orch ask --phone -> question on the phone -> answer -> ticket answered via phone, resumes (API part)."""
    ids, ph = pair(e, ["Pilatus", "Home"])
    t = e.orchj("Pilatus", "ticket", "new", "M2 phone question")["id"]
    e.orch("Pilatus", "ask", t, "Ship it?", "--option", "yes", "--option", "no", "--recommend", "yes", "--phone")
    qs = phone(e, ph, "GET", "/v1/phone/questions").json()["items"]
    mine = [q for q in qs if q["message"]["ticket"] == t]
    check(len(mine) == 1 and mine[0]["message"]["body"]["options"] == ["yes", "no"], f"phone questions: {qs}")
    a = phone(e, ph, "POST", "/v1/phone/answer", {"question_message_id": mine[0]["message"]["id"], "answer": "yes"})
    check(a.status == 201, f"answer: {a}")
    e.orch("Pilatus", "relay", "inbox")
    d = tload(e.ws("Pilatus"), t)
    q = d["questions"][0]
    check(q["answer"] == "yes" and q["via"] == "phone" and q["answered_by"].startswith("human:"), f"question: {q}")
    check(d["status"] == "active", f"ticket status {d['status']}")
    return "push + tap in the Simulator: mobile lane"


@scenario("M3")
def m3(e):
    """Same question on two phones: first answer wins, second gets 409 already_answered."""
    ids, p1 = pair(e, ["Pilatus"], "Phone one")
    _, p2 = pair(e, ["Pilatus"], "Phone two")
    t = e.orchj("Pilatus", "ticket", "new", "M3 two phones")["id"]
    e.orch("Pilatus", "ask", t, "Which one?", "--option", "a", "--option", "b", "--phone")
    q = [x for x in phone(e, p1, "GET", "/v1/phone/questions").json()["items"] if x["message"]["ticket"] == t]
    check(q and [x for x in phone(e, p2, "GET", "/v1/phone/questions").json()["items"] if x["message"]["ticket"] == t], "question not on both phones")
    mid = q[0]["message"]["id"]
    check(phone(e, p1, "POST", "/v1/phone/answer", {"question_message_id": mid, "answer": "a"}).status == 201, "first answer")
    late = phone(e, p2, "POST", "/v1/phone/answer", {"question_message_id": mid, "answer": "b"})
    check(late.status == 409 and (late.json() or {}).get("error") == "already_answered", f"late answer: {late}")
    check(not [x for x in phone(e, p2, "GET", "/v1/phone/questions").json()["items"] if x["message"]["ticket"] == t], "question still open on phone two")


@scenario("M4")
def m4(e):
    """Phone sends text to Home; Home inbox has it (voice transcription is on the phone)."""
    ids, ph = pair(e, ["Pilatus", "Home"])
    r = phone(e, ph, "POST", "/v1/phone/send", {"to": ids["Home"], "text": "buy milk (from the phone)"})
    check(r.status == 201, f"phone send: {r}")
    got = [m for m in e.orchj("Home", "relay", "inbox") if m["type"] == "text" and "buy milk" in m["body"]["text"]]
    check(got and got[0]["from"].startswith("ph_"), f"Home inbox: {got}")
    return "voice with a test audio file: mobile lane"


@scenario("M5")
def m5(e):
    """Phone cannot send to Reports (403); sign out deletes the token."""
    ids, ph = pair(e, ["Pilatus", "Home"])
    check(phone(e, ph, "POST", "/v1/phone/send", {"to": ids["Reports"], "text": "no"}).status == 403, "send to Reports not 403")
    check(phone(e, ph, "POST", "/v1/phone/signout").status == 204, "signout")
    check(phone(e, ph, "GET", "/v1/phone/workspaces").status == 401, "old token still works")


@scenario("F1")
def f1(e):
    """Fresh folder: init, publish + relay connect, ticket with evidence, phone answers, report published, link opens."""
    t0 = time.time()
    ws = "Fresh"
    e.ws(ws)
    e.connect_publish(ws)
    ids, ph = pair(e, [ws])
    t = e.orchj(ws, "ticket", "new", "Weekly report")["id"]
    e.orch(ws, "check", "add", t, "Report published")
    e.orch(ws, "ask", t, "Publish now?", "--option", "yes", "--option", "no", "--phone")
    q = [x for x in phone(e, ph, "GET", "/v1/phone/questions").json()["items"] if x["message"]["ticket"] == t][0]
    check(phone(e, ph, "POST", "/v1/phone/answer", {"question_message_id": q["message"]["id"], "answer": "yes"}).status == 201, "answer")
    e.orch(ws, "relay", "inbox")
    check(tload(e.ws(ws), t)["questions"][0]["via"] == "phone", "answer not applied")
    f = e.ws(ws) / "report.md"
    f.write_text("# Weekly report\n\nAll good.\n")
    r = e.orchj(ws, "publish", "file", str(f))
    e.orch(ws, "check", "done", t, "c1", "--evidence", json.dumps({"type": "url", "ref": r["link"].split("#")[0]}))
    e.orch(ws, "ticket", "status", t, "done")
    _, fid, key = link_parts(r["link"])
    hdr, body = opf1_decrypt(http("GET", f"{e.pub.url}/f/{fid}/blob").body, key)
    check(body == f.read_bytes(), "published report differs")
    secs = time.time() - t0
    check(secs < 900, f"took {secs:.0f}s")
    return f"{secs:.0f}s; install.sh from GitHub and the real phone/browser steps not run"



