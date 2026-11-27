"""R19: signed messages end to end (ORCH-1206). Its own file so the banned-words allowlist names only this
scenario (owner request ORCH-1027), not the whole relay scenario file."""
import json

from lib import Fail, check, http, scenario, tool_python


# ---- R19: signed messages end to end (ORCH-1206) ---------------------------------------------------------------------
# What the unit tests already cover and this does not repeat: the relay's gate per refusal code (relay/tests/
# signed_gate.rs), the receiving workspace's own check per code against a fake relay that checks nothing
# (workspace/tests/test_msgtrust.py), the Contacts block's shape and states one by one (test_contacts_trust.py) and
# the shared vectors on both sides (test_msgsig_vectors.py, relay/tests/msgsig_vectors.rs, signing_key.rs). The gap
# is the whole chain: two real workspaces, their own keys registered on the real relay, real sends and pulls.

# Run in a workspace with orch's own Python: a message as `orch relay send` makes it, never posted, plus the three
# ways it goes wrong (wrong signature over the right key id, no signature, a body changed after signing).
_R19_MAKE = r"""
import json, os, sys
from pathlib import Path
from orch import msgsig, msgtrust, relay
root, to, tag = Path.cwd(), sys.argv[1], sys.argv[2]
def sealed(text):
    return msgtrust.seal_outgoing(root, relay._build_message(root, to, "text", {"text": f"{tag} {text}"}))
wrong = sealed("forged")
forged = msgsig.sign(os.urandom(32), "msg", msgsig.read_envelope(wrong["envelope"]).signed)
forged["key_id"] = wrong["envelope"]["key_id"]  # claims the sender's real key
wrong["envelope"] = forged
missing = sealed("unsigned")
missing.pop("envelope")
changed = sealed("pay 10")
changed["body"]["text"] = f"{tag} pay 99"
print(json.dumps({"good": sealed("good"), "wrong": wrong, "missing": missing, "changed": changed}))
"""

# The receiving workspace's inbox path with the relay bypassed: the message is handed to the same pull code that
# `orch relay inbox` runs, as if a broken or broken-into relay had passed it on. Prints the ids it saved.
_R19_DROP = r"""
import json, sys
from pathlib import Path
from orch import relay
m = json.loads(sys.stdin.read())
def bypassed(root, method, path, body=None, timeout=60):
    return 200, ({"items": [m]} if method == "GET" else {})
relay._api = bypassed
ok, _ = relay._pull(Path.cwd(), 0)
print(json.dumps([x["id"] for x in ok]))
"""

# A key change signed by the workspace's current key (the relay's `key-rotate` statement, relay-api.md), with a new
# key made here; prints the request body and the new key's id and fingerprint.
_R19_ROTATE = r"""
import json, time
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from orch import msgsig, relay, signkey
root = Path.cwd()
old = signkey.public_key(root)
new = Ed25519PrivateKey.generate()
pub = new.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
st = {"v": 1, "type": "key-rotate", "from": relay._cfg(root)["workspace"], "old_key_id": msgsig.key_id(old),
      "new_public_key": msgsig.b64url(pub), "created_ms": int(time.time() * 1000)}
data = json.dumps(st, separators=(",", ":")).encode()
inp = msgsig.signature_input("key-rotate", data)
env = {"sig_v": 1, "key_id": msgsig.key_id(old), "signed": msgsig.b64url(data),
       "sig": msgsig.b64url(signkey.sign_bytes(root, inp))}
print(json.dumps({"body": {"envelope": env, "new_sig": msgsig.b64url(new.sign(inp))},
                  "key_id": msgsig.key_id(pub), "fingerprint": msgsig.fingerprint(pub)}))
"""


@scenario("R19", local_only=True)  # turns the relay's signed-only switch on for a moment: never on the live relay
def r19(e):
    """ORCH-1206 signed messages end to end: two workspaces on the local test relay, each with its own key.
    c2 two workspaces the admin paired take each other in on the first message, no Accept step (RP3 A); c3 a wrong,
    missing or changed signature is refused by the relay and, with the relay bypassed, by the receiving workspace; c4
    the Contacts data (`orch relay view --json`, the dashboard's Contacts page) shows Accepted / Not accepted yet / a
    changed key / Not valid, each with the right fingerprint. Scripted, no agent."""
    import jsonschema

    py = tool_python(e.bin)
    schema = json.loads((e.repo / "contracts" / "addon-view.schema.json").read_text(encoding="utf-8"))

    def run_py(ws, code, *args, stdin=None):
        rc, out, err = e.sh([py, "-c", code, *args], cwd=e.ws(ws), input=stdin)
        if rc != 0:
            raise Fail(f"orch python in {ws}: {(err or out).strip()[-300:]}")
        return json.loads(out)

    def contacts(ws):
        """The Contacts page's data: the relay view's `contacts` block, checked against the contract."""
        v = e.orchj(ws, "relay", "view")
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(v)
        b = next((b for b in v["blocks"] if b["type"] == "contacts"), None)
        check(b is not None, f"{ws}: no contacts block in the relay view: {[x['type'] for x in v['blocks']]}")
        return b

    def row(ws, peer):
        r = next((r for r in contacts(ws)["items"] if r["id"] == peer), None)
        check(r is not None, f"{ws}: {peer} missing on the Contacts page")
        return r

    def saved(ws, mid):
        return (e.ws(ws) / ".orch" / "inbox" / f"{mid}.json").is_file()

    def pulled(ws):
        return {m["id"] for m in e.orchj(ws, "relay", "inbox")}

    def refused_codes(ws):
        return [r["code"] for r in e.orchj(ws, "relay", "contacts", "refused")["items"]]

    # two workspaces on the relay, a rule each way, connected like a person does (no Accept yet)
    ids, tok = {}, {}
    for n in ("SigA", "SigB"):
        r = e.rel.admin.call("POST", "/admin/api/workspaces", {"name": e.label(n), "description": f"R19 {n}", "tags": ["r19"]})
        check(r.status == 201, f"relay admin add {n}: {r}")
        ids[n], tok[n] = r.json()["id"], r.json()["token"]
        e.cleanup.append(lambda i=ids[n]: e.rel.admin.call("DELETE", f"/admin/api/workspaces/{i}"))
    a, b = ids["SigA"], ids["SigB"]
    old = (e.rel.admin.call("GET", "/admin/api/rules").json() or {}).get("rules", [])
    both = {"text": True, "files": False, "delegate": False, "start": False}
    r = e.rel.admin.call("PUT", "/admin/api/rules", {"rules": old + [{"from": a, "to": b, **both}, {"from": b, "to": a, **both}]})
    check(r.status == 200, f"set rules: {r}")
    e.cleanup.append(lambda: e.rel.admin.call("PUT", "/admin/api/rules", {"rules": old}))
    for n in ("SigA", "SigB"):
        e.orch(e.ws(n), "addon", "add", "relay", "--yes")
        e.person(e.ws(n), "relay", "connect", e.rel.url, "--workspace", ids[n], "--token", tok[n])
    for n in ("SigA", "SigB"):
        e.orch(n, "relay", "refresh")
    fp = {n: e.orchj(n, "relay", "status").get("fingerprint") for n in ("SigA", "SigB")}
    check(all(fp.values()) and fp["SigA"] != fp["SigB"], f"each workspace shows its own fingerprint: {fp}")
    keys = {w["workspace"]: (w.get("key") or {}).get("fingerprint")
            for w in (e.rel.admin.call("GET", "/admin/api/signing-keys").json() or {}).get("workspaces", [])}
    check(keys.get(a) == fp["SigA"] and keys.get(b) == fp["SigB"], f"the relay holds each workspace's own key: {keys}")

    # c4 Not accepted yet, with the fingerprint the other side shows itself; c4 own fingerprint
    for me, peer, other in (("SigA", b, "SigB"), ("SigB", a, "SigA")):
        c = row(me, peer)
        check(c["state"] == "not_accepted" and c["fingerprint"] == fp[other], f"{me} sees {other}: {c}")
        check(contacts(me).get("own", {}).get("fingerprint") == fp[me], f"{me}: own fingerprint on the page")

    # c2 (RP3 A, owner 25 Nov, ORCH-2166): the admin paired A and B on the relay, so the first message goes straight
    # through with the key the refresh kept (ORCH-2349): no Accept step, no fingerprint compare. Each side takes the
    # other in on its own first message. A key that changes later is still held (c4 below, and the msgtrust tests).
    sent = e.orchj("SigA", "relay", "send", b, "R19 first contact")
    mid = sent["id"]
    check(sent.get("sent") is True, f"first send did not reach the relay: {sent}")
    check(row("SigA", b)["state"] == "not_accepted", "A took B in before B sent anything")
    check(mid in pulled("SigB") and saved("SigB", mid), "a paired workspace's first message was held (RP3 A)")
    c = row("SigB", a)
    check(c["state"] == "accepted" and c["held"] == 0 and c["fingerprint"] == fp["SigA"], f"B took A in: {c}")
    back = e.orchj("SigB", "relay", "send", a, "R19 reply")["id"]
    check(back in pulled("SigA") and saved("SigA", back), "A held B's first message (RP3 A)")
    for me, peer, other in (("SigA", b, "SigB"), ("SigB", a, "SigA")):
        c = row(me, peer)
        check(c["state"] == "accepted" and c["fingerprint"] == fp[other] and c["held"] == 0, f"c4 Accepted: {me} {c}")
    after_accept = e.orchj("SigA", "relay", "send", b, "R19 after accept")["id"]
    check(after_accept in pulled("SigB"), "an accepted contact's message did not go straight through")

    # c3 the relay refuses a wrong, missing or changed signature; nothing of it reaches B
    rapi = {"X-Orch-Workspace": a, "Authorization": f"Bearer {tok['SigA']}"}
    m = run_py("SigA", _R19_MAKE, b, "R19-relay")
    was = bool((e.rel.admin.call("GET", "/admin/api/signing-keys").json() or {}).get("require_signed"))
    sw = e.rel.admin.call("PUT", "/admin/api/signing-keys/settings", {"require_signed": True})
    check(sw.status == 200, f"relay signed-only switch: {sw}")
    try:
        got = {k: http("POST", e.rel.url + "/v1/messages", rapi, m[k]) for k in ("wrong", "missing", "changed", "good")}
    finally:
        back = e.rel.admin.call("PUT", "/admin/api/signing-keys/settings", {"require_signed": was})
    check(back.status == 200, f"relay signed-only switch put back to {was}: {back}")
    want = {"wrong": "bad_signature", "missing": "missing_signature", "changed": "signed_mismatch"}
    for k, code in want.items():
        check(got[k].status == 422 and (got[k].json() or {}).get("error") == code, f"relay on {k}: {got[k]}")
    check(got["good"].status == 201, f"relay refused the good message: {got['good']}")
    before = refused_codes("SigB")
    new = pulled("SigB")
    check(m["good"]["id"] in new and not {m[k]["id"] for k in want} & new, f"B got {new}")
    check(not any(saved("SigB", m[k]["id"]) for k in want), "a message the relay refused reached B")
    check(refused_codes("SigB") == before, "B saw a message the relay should have kept back")

    # c3 relay bypassed: the same three dropped straight into B's inbox path; B refuses each itself
    e.person_at_terminal("SigB", "relay", "contacts", "unsigned", "refuse")
    m = run_py("SigA", _R19_MAKE, b, "R19-bypass")
    for k, code in want.items():
        kept = run_py("SigB", _R19_DROP, stdin=json.dumps(m[k]))
        check(kept == [] and not saved("SigB", m[k]["id"]), f"B handled a {k} signature with the relay bypassed")
        check(refused_codes("SigB")[-1] == code, f"B refused {k} as {refused_codes('SigB')[-1:]}, want {code}")
    check(run_py("SigB", _R19_DROP, stdin=json.dumps(m["good"])) == [m["good"]["id"]], "bypass path lost a good message")

    # c4 Not valid: B shows A as not valid (forged messages in A's name) with A's fingerprint and the count
    c = row("SigB", a)
    check(c["state"] == "not_valid" and c["fingerprint"] == fp["SigA"] and c.get("refused") == len(want), f"c4 Not valid: {c}")

    # c4 a changed key: B's key change (signed by its old key) approved on the relay; A shows the new key with the
    # accepted one beside it and no longer counts it as accepted (the relay's yes is no Accept). Today the workspace
    # says new_key for every key change; `changed` (vouched by the old key) is the contract's word for this case.
    rot = run_py("SigB", _R19_ROTATE)
    r = http("POST", e.rel.url + "/v1/me/signing-key/change", {"X-Orch-Workspace": b, "Authorization": f"Bearer {tok['SigB']}"}, rot["body"])
    check(r.status == 202 and (r.json() or {}).get("kind") == "signed", f"key change request: {r}")
    r = e.rel.admin.call("POST", f"/admin/api/signing-keys/{b}/approve", {"key_id": rot["key_id"], "kind": "signed"})
    check(r.status == 200, f"admin approve key change: {r}")
    e.orch("SigA", "relay", "refresh")
    c = row("SigA", b)
    check(c["state"] in ("new_key", "changed") and c["fingerprint"] == rot["fingerprint"]
          and c.get("old_fingerprint") == fp["SigB"], f"c4 changed key: {c}")
    return "paired workspaces trusted from the first message (RP3 A); relay and workspace refuse wrong/missing/changed; Contacts states"
