"""Several people in one workspace (ORCH-1164, step 6 of the first slice): the two-person test.

Two people, two phones, one ticket, against the real local relay and a real workspace. Lea (write) writes on the
ticket from her phone, her answer to the ticket's card is refused, Max (write, decide) answers it from his phone, and
once the owner cuts Lea's phone (and then removes it on the relay) her phone is refused. Its own workspace "Team",
so the person list it turns on never changes what the other phone scenarios see in Pilatus."""
from __future__ import annotations

import json

from lib import check, http, scenario
from scenarios_phone_v3 import ph_call, send, uid
from scenarios_ws import tload

WS = "Team"


def _pair(e, wid, label):
    """A phone paired with the Team workspace only (the relay admin page's pairing, as the owner does it)."""
    r = e.rel.admin.call("POST", "/admin/api/phones", {"name": label, "workspaces": [wid]})
    check(r.status == 201, f"add phone {label}: {r}")
    code = r.json()["link"].split("code=")[1]
    p = http("POST", e.rel.url + "/v1/phone/pair", None, {"code": code, "name": label})
    check(p.status == 201, f"pair {label}: {p}")
    pj = p.json()
    e.cleanup.append(lambda i=pj["phone_id"]: e.rel.admin.call("DELETE", f"/admin/api/phones/{i}"))
    return pj["phone_id"], pj["token"]


def _people(e):
    return json.loads((e.ws(WS) / ".orch" / "local" / "people.json").read_text())


def _refused(e):
    p = e.ws(WS) / ".orch" / "local" / "people-refused.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _tickets(e):
    out = []
    for p in sorted((e.ws(WS) / ".orch" / "tickets").glob("t_*.json")):
        t = json.loads(p.read_text())
        if not t.get("general"):
            out.append(t)
    return out


def _open_question(e, ph, tid):
    qs = ph_call(e, ph, "GET", "/v1/phone/questions").json()["items"]
    mine = [q for q in qs if q["message"].get("ticket") == tid]
    check(mine, f"no open question for {tid} on the phone: {qs}")
    return mine[0]["message"]["id"]


@scenario("V3-P9", local_only=True)
def people1(e):
    """Two people, two phones, one ticket: Lea writes, Lea's approve is refused, Max approves, a cut phone and a phone
    removed on the relay are refused; the ticket names Lea and Max."""
    wid = e.connect_relay(WS, tags=["team"], desc="Two people, one workspace")[0]
    lea_ph = _pair(e, wid, "Lea phone")
    max_ph = _pair(e, wid, "Max phone")
    e.orch(WS, "relay", "refresh")  # the workspace learns which phones are paired

    # the owner sets the people up (Settings > People does the same)
    e.person(WS, "people", "on", "--name", "Sev")
    e.person(WS, "people", "add", "Lea")
    e.person(WS, "people", "add", "Max", "--rights", "write,decide")
    e.person(WS, "people", "tie", lea_ph[0], "Lea")
    e.person(WS, "people", "tie", max_ph[0], "Max")
    ids = {p["name"]: p["id"] for p in _people(e)["people"]}
    check({"Sev", "Lea", "Max"} <= set(ids), f"people: {ids}")

    # 1. Lea writes: her text makes the one ticket, its history names her person and her phone
    before = {t["id"] for t in _tickets(e)}
    r = send(e, lea_ph, wid, text="Please book the team dinner for Friday")
    check(r.status == 201, f"Lea's text: {r}")
    e.orch(WS, "relay", "inbox")
    made = [t for t in _tickets(e) if t["id"] not in before]
    check(len(made) == 1, f"tickets made by Lea's text: {[t['title'] for t in made]}")
    tid = made[0]["id"]
    r = send(e, lea_ph, wid, text="Eight people, near the office", ticket=tid)
    check(r.status == 201, f"Lea's second text: {r}")
    e.orch(WS, "relay", "inbox")
    phone_lines = [h for h in tload(e.ws(WS), tid)["history"] if h.get("via") == "phone"]
    check(len(phone_lines) >= 2 and all(h.get("person") == ids["Lea"] and h.get("device") == lea_ph[0]
                                        for h in phone_lines), f"Lea's lines: {phone_lines}")

    # 2. the ticket asks; Lea may only write, so her answer is refused and the card stays open
    e.orch(WS, "ask", tid, "Book the table at Rossi for Friday 19:00?", "--option", "yes", "--option", "no",
           "--recommend", "yes", "--phone")
    a = ph_call(e, lea_ph, "POST", "/v1/phone/answer", {"question_message_id": _open_question(e, lea_ph, tid),
                                                         "answer": "yes"})
    check(a.status == 201, f"the relay takes Lea's answer (the workspace decides): {a}")
    e.orch(WS, "relay", "inbox")
    q = tload(e.ws(WS), tid)["questions"][0]
    check(q.get("answer") is None, f"Lea's answer was taken: {q}")
    check("Lea may not decide" in _refused(e)[-1]["why"], f"refused: {_refused(e)[-1:]}")

    # 3. Max may decide: the card goes out again and his answer counts, recorded as Max via his phone
    a = ph_call(e, max_ph, "POST", "/v1/phone/answer", {"question_message_id": _open_question(e, max_ph, tid),
                                                         "answer": "yes"})
    check(a.status == 201, f"Max's answer: {a}")
    e.orch(WS, "relay", "inbox")
    q = tload(e.ws(WS), tid)["questions"][0]
    check((q.get("answer"), q.get("answered_by"), q.get("via")) == ("yes", "human:" + ids["Max"], "phone"),
          f"Max's answer: {q}")
    shown = e.orch(WS, "ticket", "show", tid)[1]
    check("- yes (Max)" in shown and "human:pr_" not in shown, f"the ticket does not name Max: {shown[-600:]}")

    # 4. Lea's phone is lost. A text it sent just before the owner cuts it is refused by the workspace (nothing is
    #    written), and from the cut on the relay refuses the phone too (the cut takes Team off its list there)
    r = send(e, lea_ph, wid, text="Cancel the dinner", ticket=tid)
    check(r.status == 201, f"Lea's text before the cut: {r}")
    e.person(WS, "people", "cut", lea_ph[0])
    n = len(tload(e.ws(WS), tid)["history"])
    e.orch(WS, "relay", "inbox")
    t = tload(e.ws(WS), tid)
    check("Cancel the dinner" not in json.dumps(t), "a cut phone's text landed on the ticket")
    check("cut off" in _refused(e)[-1]["why"], f"refused: {_refused(e)[-1:]}")
    check(_refused(e)[-1].get("device") == lea_ph[0], f"refused line names the phone: {_refused(e)[-1:]}")
    check("Cancel the dinner" not in json.dumps(_refused(e)), "the refused list keeps message content")
    r = send(e, lea_ph, wid, text="Cancel it please", ticket=tid)
    check(r.status == 403, f"the relay still takes texts of a cut phone: {r}")
    r = send(e, max_ph, wid, text="Booked, see you Friday", ticket=tid)
    check(r.status == 201, f"Max's text: {r}")
    e.orch(WS, "relay", "inbox")
    t = tload(e.ws(WS), tid)
    check(len(t["history"]) > n and "Booked, see you Friday" in json.dumps(t), "Max's text did not land")

    # 5. the owner removes Lea's phone on the relay admin page: the relay no longer knows it at all
    check(e.rel.admin.call("DELETE", f"/admin/api/phones/{lea_ph[0]}").status in (200, 204), "remove phone")
    r = send(e, lea_ph, wid, text="Still there?", client_id=uid())
    check(r.status == 401, f"a removed phone is still let in by the relay: {r}")
    seen = _dashboard(e, tid)
    return "Lea writes, her approve refused, Max approves, a cut and a removed phone refused" + seen


def _dashboard(e, tid) -> str:
    """The owner's dashboard after the story (Settings > People and the ticket), pictures at 1280, 1920 and 390 into
    E2E_SHOTS. Needs node and Playwright; without them the relay part above still counts."""
    import os

    from scenarios_look import browser_half, find_node, find_pw_dir

    if not find_pw_dir() or not find_node(e.path):
        return "; dashboard not checked (no browser here)"
    rc, out, err = e.addon_add(WS, "dashboard")
    check(rc == 0, f"addon add dashboard: {(err or out)[-300:]}")
    try:
        e.orch(WS, "start", "--no-open")
        url = next((a["url"] for r in e.orchj(WS, "status") for a in r["addons"] if a["addon"] == "dashboard"), "")
        launch = next((x["url"] for x in e.orchj(WS, "start", "--print-launch-url").get("launch") or []
                       if x.get("addon") == "dashboard"), "")
        check(url and "#launch=" in launch, "the dashboard did not start with a sign-in link")
        got = browser_half(e, "dash_people.cjs", url, launch, tid, os.environ.get("E2E_SHOTS", ""))
        check(not got["errors"] and got["noOverflow"], f"dashboard: errors or a cut-off layout: {got}")
        return f"; dashboard names Lea and Max ({len(got['shots'])} pictures)"
    finally:
        e.sh(["orch", "stop", "--all"], cwd=e.path_of(WS))
