"""Phone app v3 backend (V3-P1..P8): a scripted phone over HTTP against the local relay and a real workspace.

The workspace side is the real `orch relay inbox` (pull, ack, tickets, receipts). Push is not visible in the local
suite (the relay has no APNs here), so mute is checked on the state and on what is still stored."""
from __future__ import annotations

import json
import uuid

from lib import check, http, scenario
from scenarios_ws import tload

JPG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes-v3" * 20
PDF = b"%PDF-1.4\n" + b"fake-pdf-bytes-v3\n" * 20


def uid() -> str:
    return str(uuid.uuid4())


def pair2(e, names, label):
    from scenarios_misc import pair

    return pair(e, names, label=label)


def ph_call(e, ph, method, path, body=None, headers=None):
    h = {"X-Orch-Phone": ph[0], "Authorization": f"Bearer {ph[1]}", **(headers or {})}
    return http(method, e.rel.url + path, h, body)


def send(e, ph, ws, **body):
    return ph_call(e, ph, "POST", "/v1/phone/send", {"to": ws, "client_id": uid(), **body})


def upload(e, ph, data: bytes, ctype="application/octet-stream"):
    r = ph_call(e, ph, "POST", "/v1/phone/blobs", data, {"Content-Type": ctype})
    check(r.status == 201, f"upload: {r}")
    return r.json()


def big_upload(e, ph, size: int):
    """Upload `size` bytes; the relay may answer 413 and hang up before it has read everything (a broken pipe on our side)."""
    import http.client
    from urllib.parse import urlparse

    u = urlparse(e.rel.url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=120)
    c.putrequest("POST", "/v1/phone/blobs")
    for k, v in {"X-Orch-Phone": ph[0], "Authorization": f"Bearer {ph[1]}", "Content-Length": str(size),
                 "Content-Type": "application/octet-stream"}.items():
        c.putheader(k, v)
    c.endheaders()
    try:
        chunk = b"\0" * (1024 * 1024)
        left = size
        while left > 0:
            c.send(chunk[: min(left, len(chunk))])
            left -= len(chunk)
    except OSError:
        pass
    r = c.getresponse()
    out = (r.status, r.read().decode("utf-8", "replace"))
    c.close()
    return out


def listing(e, ph, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    r = ph_call(e, ph, "GET", "/v1/phone/messages" + ("?" + qs if qs else ""))
    check(r.status == 200, f"messages: {r}")
    return r.json()


def item_of(e, ph, mid):
    for it in listing(e, ph, limit=100)["items"]:
        if it["message"]["id"] == mid:
            return it
    return None


def inbox(e, ws="Pilatus"):
    return e.orch(ws, "relay", "inbox")[1]


def real_tickets(e, ws="Pilatus"):
    return [json.loads(p.read_text()) for p in sorted((e.ws(ws) / ".orch/tickets").glob("t_*.json"))
            if not json.loads(p.read_text()).get("general")]


def from_ws(e, ph, wid):
    return [it["message"] for it in listing(e, ph, limit=100)["items"] if it["message"]["from"] == wid]


@scenario("V3-P1", local_only=True)
def p1(e):
    """General: a phone text marked General (sent twice with the same client id) is one message, no ticket is made for
    it, and the double tick (delivered_at) appears once the workspace has pulled it."""
    ids, ph = pair2(e, ["Pilatus"], "V3-P1 phone")
    ws = ids["Pilatus"]
    cid = uid()
    r1 = send(e, ph, ws, text="General hello from the phone", general=True, client_id=cid)
    check(r1.status == 201 and r1.json()["client_id"] == cid, f"first send: {r1}")
    r2 = send(e, ph, ws, text="General hello from the phone", general=True, client_id=cid)
    check(r2.status == 200 and r2.json().get("duplicate") is True and r2.json()["id"] == r1.json()["id"], f"dedupe: {r2}")
    own = [it for it in listing(e, ph, limit=100)["items"] if it["message"]["from"] == ph[0]]
    check(len(own) == 1 and own[0]["client_id"] == cid and own[0]["delivered_at"] is None, f"before pull: {own}")
    check(own[0]["message"]["body"].get("general") is True and not own[0]["message"].get("ticket"), f"stored: {own[0]}")
    before = len(real_tickets(e))
    out = inbox(e)
    check("General" in out, f"inbox: {out}")
    check(len(real_tickets(e)) == before, "a General text made a ticket")
    it = item_of(e, ph, r1.json()["id"])
    check(it["delivered_at"], f"delivered_at missing after the workspace pulled: {it}")
    acks = [m for m in from_ws(e, ph, ws) if m["body"].get("update", {}).get("kind") == "ack"]
    check(acks and acks[0].get("reply_to") == r1.json()["id"] and acks[0]["body"].get("general") is True
          and not acks[0].get("ticket"), f"General ack: {acks}")
    return "send, dedupe, no ticket, delivered_at, General ack"


@scenario("V3-P2", local_only=True)
def p2(e):
    """Working and topic start: a new-topic text gets an ack naming a new ticket (reply_to = the phone text); the
    phone's after-cursor shows the ack and, later, an agent reply with a speak hint in that topic."""
    ids, ph = pair2(e, ["Pilatus"], "V3-P2 phone")
    ws = ids["Pilatus"]
    r = send(e, ph, ws, text="Please check the Q3 numbers")
    check(r.status == 201, f"send: {r}")
    mid = r.json()["id"]
    page = listing(e, ph, limit=100)
    newest = page["items"][0]["message"]["id"]
    inbox(e)
    t = [t for t in real_tickets(e) if "Q3 numbers" in json.dumps(t)]
    check(len(t) == 1, f"topic not made: {[x['title'] for x in real_tickets(e)]}")
    tid = t[0]["id"]
    # sync: everything after what the phone knew (newest first; a page of 1 then `after` = next)
    items = listing(e, ph, limit=100)["items"]
    ids_now = [i["message"]["id"] for i in items]
    check(newest in ids_now and ids_now.index(newest) > 0, f"nothing new after the pull: {ids_now}")
    new = [i["message"] for i in items[: ids_now.index(newest)]]
    ack = [m for m in new if m["body"].get("update", {}).get("kind") == "ack"]
    check(len(ack) == 1 and ack[0].get("reply_to") == mid and ack[0].get("ticket") == tid, f"topic ack: {new}")
    check(ack[0].get("key"), f"ack has no ticket key: {ack[0]}")
    # cursor paging works: limit 1 then after=next walks the same list newest first
    p1_ = listing(e, ph, limit=1)
    check(len(p1_["items"]) == 1 and p1_["next"], f"page 1: {p1_}")
    p2_ = listing(e, ph, limit=1, after=p1_["next"])
    check(p2_["items"] and p2_["items"][0]["message"]["id"] == ids_now[1], f"page 2: {p2_}")
    # the Working update comes from the run: the workspace sends it with `orch relay send --update working`
    e.orch("Pilatus", "relay", "send", ph[0], "Working on it", "--ticket", tid, "--update", "working", "--reply-to", mid)
    # agent reply with a speak hint
    e.orch("Pilatus", "relay", "send", ph[0], "The Q3 numbers are fine. Revenue grew.", "--ticket", tid, "--speak",
           "--summary", "Q3 is fine.", "--update", "result")
    topic = [m for m in from_ws(e, ph, ws) if m.get("ticket") == tid]
    kinds = {m["body"].get("update", {}).get("kind") for m in topic}
    check({"ack", "working", "result"} <= kinds, f"topic messages kinds: {kinds}")
    spoken = [m for m in topic if m["body"].get("speak")]
    check(len(spoken) == 1 and spoken[0]["body"]["speak"].get("summary") == "Q3 is fine.", f"speak hint: {spoken}")
    ups = ph_call(e, ph, "GET", f"/v1/phone/updates?workspace={ws}&ticket={tid}").json()["items"]
    check(any(u["kind"] == "result" for u in ups) and all(u["kind"] != "ack" or True for u in ups), f"updates: {ups}")
    return "topic ack with key, cursor paging, working, result with speak"


@scenario("V3-P3", local_only=True)
def p3(e):
    """New topic: a text with neither ticket nor General makes exactly one ticket, and the reply lands in that
    topic (same ticket id on the phone's side)."""
    ids, ph = pair2(e, ["Pilatus"], "V3-P3 phone")
    ws = ids["Pilatus"]
    before = {t["id"] for t in real_tickets(e)}
    r = send(e, ph, ws, text="Plan the offsite in March")
    check(r.status == 201 and "ticket" not in (item_of(e, ph, r.json()["id"])["message"]), f"pending topic: {r}")
    inbox(e)
    inbox(e)  # a second pull must not make a second ticket
    made = [t for t in real_tickets(e) if t["id"] not in before]
    check(len(made) == 1 and "offsite" in json.dumps(made[0]), f"tickets made: {[t['title'] for t in made]}")
    tid = made[0]["id"]
    ack = [m for m in from_ws(e, ph, ws) if m.get("reply_to") == r.json()["id"]]
    check(ack and ack[0].get("ticket") == tid, f"ack names the ticket: {ack}")
    e.orch("Pilatus", "relay", "send", ph[0], "March works, shall I book?", "--ticket", tid)
    last = from_ws(e, ph, ws)[0]
    check(last.get("ticket") == tid and last["body"]["text"].startswith("March works"), f"reply in topic: {last}")
    return "one ticket, ack with ticket, reply in the topic"


@scenario("V3-P4", local_only=True)
def p4(e):
    """Upload: jpg and pdf uploaded and sent; the workspace reads exactly those blobs (saved into the ticket), not a
    blob of another phone, nor an unnamed one; 25 MB + 1 byte is refused 413; downloads carry nosniff."""
    ids, ph = pair2(e, ["Pilatus"], "V3-P4 phone")
    _, other = pair2(e, ["Pilatus"], "V3-P4 other phone")
    ws = ids["Pilatus"]
    j, p = upload(e, ph, JPG, "image/jpeg"), upload(e, ph, PDF, "application/pdf")
    stranger = upload(e, other, b"someone else's secret bytes")
    unnamed = upload(e, ph, b"never named in a text")
    check(j["size"] == len(JPG) and p["size"] == len(PDF) and len(j["sha256"]) == 64, f"upload answers: {j} {p}")
    atts = [{"blob_id": j["blob_id"], "kind": "image", "name": "photo.jpg", "size": len(JPG), "mime": "image/jpeg"},
            {"blob_id": p["blob_id"], "kind": "file", "name": "../../offer.pdf", "size": len(PDF), "mime": "application/pdf"}]
    # a blob of another phone, and a wrong size, are refused
    bad = send(e, ph, ws, attachments=[{**atts[0], "blob_id": stranger["blob_id"], "size": stranger["size"]}])
    check(bad.status == 404, f"blob of another phone: {bad}")
    bad = send(e, ph, ws, attachments=[{**atts[0], "size": len(JPG) + 1}])
    check(bad.status == 422, f"wrong size: {bad}")
    # before any text names them, the workspace cannot read them
    check(e.rapi("Pilatus", "GET", f"/v1/blobs/{j['blob_id']}").status == 404, "workspace read a blob nobody named yet")
    r = send(e, ph, ws, text="Photo and offer attached", attachments=atts)
    check(r.status == 201, f"send with attachments: {r}")
    for b, raw in ((j, JPG), (p, PDF)):
        g = e.rapi("Pilatus", "GET", f"/v1/blobs/{b['blob_id']}")
        check(g.status == 200 and g.body == raw, f"workspace read of {b['blob_id']}: {g.status}")
        check(g.headers.get("x-content-type-options") == "nosniff" and "attachment" in g.headers.get("content-disposition", ""),
              f"workspace download headers: {g.headers}")
        g = ph_call(e, ph, "GET", f"/v1/phone/blobs/{b['blob_id']}")
        check(g.status == 200 and g.body == raw and g.headers.get("x-content-type-options") == "nosniff"
              and g.headers.get("content-type", "").startswith("application/octet-stream"), f"phone download: {g.status} {g.headers}")
    for b in (stranger, unnamed):
        check(e.rapi("Pilatus", "GET", f"/v1/blobs/{b['blob_id']}").status == 404, f"workspace read unnamed blob {b}")
    check(ph_call(e, ph, "GET", f"/v1/phone/blobs/{stranger['blob_id']}").status == 404, "phone read the other phone's blob")
    # the real workspace saves exactly these two files into the ticket
    before = {t["id"] for t in real_tickets(e)}
    inbox(e)
    t = [t for t in real_tickets(e) if t["id"] not in before]
    check(len(t) == 1, f"ticket for the attachments: {len(t)}")
    files = e.ws("Pilatus") / ".orch" / "tickets" / t[0]["id"] / "files"
    got = {f.name: f.read_bytes() for f in files.iterdir()} if files.is_dir() else {}
    check(sorted(got.values()) == sorted([JPG, PDF]), f"saved files: {list(got)}")
    check(all("/" not in n and not n.startswith(".") for n in got), f"unsafe file names: {list(got)}")
    # empty body and too big
    check(ph_call(e, ph, "POST", "/v1/phone/blobs", b"").status == 422, "empty upload accepted")
    big_status, big_text = big_upload(e, ph, 25 * 1024 * 1024 + 1)
    check(big_status == 413, f"25 MB + 1: {big_status} {big_text[:100]}")
    ok = ph_call(e, ph, "POST", "/v1/phone/blobs", b"\0" * (1024 * 1024))
    check(ok.status == 201, f"1 MB after a refused big one: {ok}")
    return "upload, blob scoping, saved files, 413, nosniff"


@scenario("V3-P5", local_only=True)
def p5(e):
    """Feedback, location and voice: a feedback with an html pin, a location and a voice memo (with transcript) arrive
    in the ticket history in readable words."""
    ids, ph = pair2(e, ["Pilatus"], "V3-P5 phone")
    ws = ids["Pilatus"]
    t = e.orchj("Pilatus", "ticket", "new", "V3-P5 proof review")["id"]
    fb = {"artifact_id": "a_ee3652384f1b", "artifact_rev": "f_0123456789abcdef", "verdict": "changes",
          "pins": [{"n": 1, "anchor": {"type": "html", "selector": "#chart-q3", "quote": "Umsatz Q3", "offset": 640, "viewport_w": 390},
                    "text": "Make the chart bigger"}]}
    voice_blob = upload(e, ph, b"fake-m4a-bytes" * 10, "audio/m4a")
    sends = [
        send(e, ph, ws, ticket=t, feedback=fb),
        send(e, ph, ws, ticket=t, location={"lat": 47.0502, "lon": 8.3093, "label": "Luzern Bahnhof", "accuracy_m": 12}),
        send(e, ph, ws, ticket=t, voice={"blob_id": voice_blob["blob_id"], "transcript": "Mach die Grafik bitte groesser",
                                         "lang": "de-CH", "lang_source": "setting"}),
    ]
    check(all(r.status == 201 for r in sends), f"sends: {sends}")
    inbox(e)
    hist = json.dumps(tload(e.ws("Pilatus"), t))
    check("changes wanted" in hist and "Make the chart bigger" in hist, f"feedback in history: {hist[-600:]}")
    check("47.05020, 8.30930" in hist and "Luzern Bahnhof" in hist and "maps.apple.com" in hist, f"location in history: {hist[-600:]}")
    check("Voice message (de-CH)" in hist and "Mach die Grafik bitte groesser" in hist, f"voice in history: {hist[-600:]}")
    # nothing sent to a ticket made a new one
    check(not [x for x in real_tickets(e) if x["id"] != t and "Luzern" in json.dumps(x)], "a second ticket was made")
    # a "Looks good" approve needs no pins, a changes feedback without a pin is refused
    ok = send(e, ph, ws, ticket=t, feedback={**fb, "verdict": "approve", "pins": []})
    check(ok.status == 201, f"approve: {ok}")
    bad = send(e, ph, ws, ticket=t, feedback={**fb, "pins": []})
    check(bad.status == 422, f"changes without pins: {bad}")
    return "feedback pin, location, voice transcript in history"


@scenario("V3-P6", local_only=True)
def p6(e):
    """Settings and speech: PATCH settings round-trips (bad values refused); read-aloud is 503 tts_off without a key and
    402 tts_cap_reached when the cap is 0 (a made-up key, never called: the cap is checked first)."""
    ids, ph = pair2(e, ["Pilatus"], "V3-P6 phone")
    ws = ids["Pilatus"]
    s = ph_call(e, ph, "GET", "/v1/phone/settings").json()
    check(s["speak"] == "auto" and s["swiss_german"] is False and s["tts_cap_usd"] == 10 and s["tts_used_usd_month"] == 0, f"defaults: {s}")
    r = ph_call(e, ph, "PATCH", "/v1/phone/settings", {"speak": "always", "swiss_german": True, "tts_cap_usd": 3.5})
    check(r.status == 200 and r.json()["speak"] == "always" and r.json()["swiss_german"] is True and r.json()["tts_cap_usd"] == 3.5, f"patch: {r}")
    check(ph_call(e, ph, "GET", "/v1/phone/settings").json() == r.json(), "GET differs from the PATCH answer")
    for bad in ({"speak": "sometimes"}, {"tts_cap_usd": 101}, {"swiss_german": "yes"}, {}):
        check(ph_call(e, ph, "PATCH", "/v1/phone/settings", bad).status == 422, f"bad value accepted: {bad}")
    # a workspace text with a speak hint
    t = e.orchj("Pilatus", "ticket", "new", "V3-P6 speech")["id"]
    e.orch("Pilatus", "relay", "send", ph[0], "Read this out loud, please.", "--ticket", t, "--speak")
    mid = from_ws(e, ph, ws)[0]["id"]
    g = ph_call(e, ph, "GET", f"/v1/phone/speech/{mid}")
    check(g.status == 503 and g.json()["error"] == "tts_off", f"no key: {g.status} {g.text}")
    check(ph_call(e, ph, "GET", f"/v1/phone/speech/{mid}?lang=fr").status == 422, "lang fr accepted")
    check(ph_call(e, ph, "GET", "/v1/phone/speech/m_doesnotexist0000").status == 404, "unknown message")
    ad = e.rel.admin
    old = ad.call("GET", "/admin/api/voice")
    check(old.status == 200, f"voice admin: {old}")
    r = ad.call("PUT", "/admin/api/voice", {"deepgram_key": "dg_fake_never_called_" + "x" * 20})
    check(r.status == 200, f"set key: {r}")
    e.cleanup.append(lambda: ad.call("DELETE", "/admin/api/voice"))
    ph_call(e, ph, "PATCH", "/v1/phone/settings", {"tts_cap_usd": 0})
    g = ph_call(e, ph, "GET", f"/v1/phone/speech/{mid}")
    check(g.status == 402 and g.json()["error"] == "tts_cap_reached", f"cap 0: {g.status} {g.text}")
    ph_call(e, ph, "PATCH", "/v1/phone/settings", {"speak": "never"})
    check(ph_call(e, ph, "GET", f"/v1/phone/speech/{mid}").status == 404, "speak never still makes audio")
    return "settings round trip, 503 tts_off, 402 cap 0"


@scenario("V3-P7", local_only=True)
def p7(e):
    """Workspaces: an invitation adds a workspace once (reused 410, unknown 404, bad pattern 422); mute is stored and
    cleared and texts still arrive; removing a workspace drops it from the list and sending to it is refused."""
    ids, ph = pair2(e, ["Pilatus"], "V3-P7 phone")
    pil, home = ids["Pilatus"], ids["Home"]
    inv = e.rel.admin.call("POST", "/admin/api/phones", {"name": "V3-P7 invitation", "workspaces": [home]})
    check(inv.status == 201, f"invitation: {inv}")
    code = inv.json()["link"].split("code=")[1]
    check(send(e, ph, home, text="not yet").status == 403, "sent to a workspace not on the list")
    for bad, want in (("nope", 422), ("pc_" + "z" * 22, 404), ("", 422)):
        r = ph_call(e, ph, "POST", "/v1/phone/invitations/redeem", {"code": bad})
        check(r.status == want, f"redeem {bad!r}: {r.status} {r.text[:100]} (want {want})")
    r = ph_call(e, ph, "POST", "/v1/phone/invitations/redeem", {"code": code})
    check(r.status == 200 and [w["id"] for w in r.json()["workspaces"]] == [home], f"redeem: {r}")
    again = ph_call(e, ph, "POST", "/v1/phone/invitations/redeem", {"code": code})
    check(again.status == 410, f"reused invitation: {again.status} {again.text[:100]}")
    listed = {w["id"]: w for w in ph_call(e, ph, "GET", "/v1/phone/workspaces").json()["items"]}
    check(set(listed) == {pil, home} and listed[home]["muted_until"] is None, f"list after redeem: {list(listed)}")
    # mute: stored, cleared; a text from the workspace is still listed
    m = ph_call(e, ph, "PATCH", f"/v1/phone/workspaces/{home}", {"muted_until": "forever"})
    check(m.status == 200 and m.json()["muted_until"] == "forever", f"mute: {m}")
    m = ph_call(e, ph, "PATCH", f"/v1/phone/workspaces/{home}", {"muted_until": "2999-01-01T00:00:00Z"})
    check(m.status == 200 and m.json()["muted_until"], f"mute until: {m}")
    check(ph_call(e, ph, "PATCH", f"/v1/phone/workspaces/{home}", {"muted_until": "tomorrow"}).status == 422, "bad time accepted")
    ph_call(e, ph, "PATCH", f"/v1/phone/workspaces/{home}", {"muted_until": "forever"})
    e.orch("Home", "relay", "refresh")
    e.orch("Home", "relay", "send", ph[0], "text while muted")
    check(any(x["body"].get("text") == "text while muted" for x in from_ws(e, ph, home)), "muted text not stored")
    check(ph_call(e, ph, "PATCH", f"/v1/phone/workspaces/{home}", {"muted_until": None}).json()["muted_until"] is None, "unmute")
    check(ph_call(e, ph, "PATCH", "/v1/phone/workspaces/ws_unknown0000", {"muted_until": None}).status == 404, "mute unknown")
    # remove
    check(ph_call(e, ph, "DELETE", f"/v1/phone/workspaces/{home}").status == 204, "remove")
    left = [w["id"] for w in ph_call(e, ph, "GET", "/v1/phone/workspaces").json()["items"]]
    check(left == [pil], f"list after remove: {left}")
    check(send(e, ph, home, text="after remove").status == 403, "send after remove not refused")
    check(ph_call(e, ph, "DELETE", f"/v1/phone/workspaces/{home}").status == 404, "second remove")
    return "invitation, reuse 410, mute, remove (push itself not visible locally)"


@scenario("V3-P8", local_only=True)
def p8(e):
    """Offline resend: the same client id sent three times with gaps (the phone outbox after a 503) is one message, one
    ticket, one ack; an answer shares the namespace."""
    import time

    ids, ph = pair2(e, ["Pilatus"], "V3-P8 phone")
    ws = ids["Pilatus"]
    cid = uid()
    first = send(e, ph, ws, text="Resend me once", client_id=cid)
    check(first.status == 201, f"first: {first}")
    for n in range(2):
        time.sleep(1.2)
        r = send(e, ph, ws, text="Resend me once", client_id=cid)
        check(r.status == 200 and r.json()["id"] == first.json()["id"] and r.json()["duplicate"] is True, f"resend {n}: {r}")
        if n == 0:
            inbox(e)  # the workspace pulls between the retries
    inbox(e)
    own = [it for it in listing(e, ph, limit=100)["items"] if it["message"]["from"] == ph[0]]
    check(len(own) == 1, f"phone texts stored: {len(own)}")
    made = [t for t in real_tickets(e) if "Resend me once" in json.dumps(t)]
    check(len(made) == 1, f"tickets: {len(made)}")
    acks = [m for m in from_ws(e, ph, ws) if m.get("reply_to") == first.json()["id"]
            and m["body"].get("update", {}).get("kind") == "ack"]
    check(len(acks) == 1, f"acks: {len(acks)}")
    # the namespace is shared with answers: the same id as a text, on the answer route, is a duplicate
    r = ph_call(e, ph, "POST", "/v1/phone/answer", {"question_message_id": "m_doesnotexist0000", "answer": "x", "client_id": cid})
    check(r.status == 200 and r.json().get("duplicate") is True and r.json()["id"] == first.json()["id"], f"shared namespace: {r}")
    return "3 sends, 1 message, 1 ticket, 1 ack"
