"""Check every contract example (tickets incl. ext.automation, run records, pending input, Needs you rows,
agent adapters and their config entries, messages, workspaces, add-on manifests and views), the publish
crypto vectors, and the phone API v3 (every /v1/phone example in review/relay-api.examples.json against
phone-api.schema.json, plus vectors/phone-v3-v1.json). Every examples/<kind>/ folder needs at least one valid-* and one invalid-* file.

Run: uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py
"""
import base64
import hashlib
import json
import re
import struct
import sys
import tomllib
import types
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

HERE = Path(__file__).parent
fails = []


_CATS = {}


def _class_body(cat):
    """Python's re has no \\p{..}: expand a Unicode category (L, Zs, ...) to explicit ranges."""
    if not _CATS:
        for cp in range(sys.maxunicode + 1):
            c = unicodedata.category(chr(cp))
            _CATS.setdefault(c, []).append(cp)
            _CATS.setdefault(c[0], []).append(cp)
    out, cps = [], _CATS.get(cat, [])
    i = 0
    while i < len(cps):
        j = i
        while j + 1 < len(cps) and cps[j + 1] == cps[j] + 1:
            j += 1
        a, b = cps[i], cps[j]
        out.append(re.escape(chr(a)) if a == b else f"{re.escape(chr(a))}-{re.escape(chr(b))}")
        i = j + 1
    return "".join(out)


def _expand(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pattern" and isinstance(v, str) and "\\p{" in v:
                node[k] = re.sub(r"\\p\{(\w+)\}", lambda m: _class_body(m.group(1)), v)
            else:
                _expand(v)
    elif isinstance(node, list):
        for v in node:
            _expand(v)
    return node


def validator(name):
    schema = _expand(json.loads((HERE / f"{name}.schema.json").read_text()))
    return Draft202012Validator(schema, format_checker=FormatChecker())


V = {
    "ticket": validator("ticket"),
    "message": validator("message"),
    "workspaces": validator("workspaces"),
    "addon-manifest": validator("addon-manifest"),
    "addon-view": validator("addon-view"),
    "run": validator("run"),
    "run-pending": validator("run-pending"),
    "needs": validator("needs"),
    "agent-adapter": validator("agent-adapter"),
    "run-event": validator("addons/focus/run-event"),
    "automation-ext": validator("addons/automation/ext"),
    "focus-ext": validator("addons/focus/ext"),
}
# The [workspace] agent + [agents.<name>] part of .orch/config.toml: a $def of agent-adapter.schema.json.
_adapters = json.loads((HERE / "agent-adapter.schema.json").read_text())
V["agent-config"] = Draft202012Validator(
    {"$ref": "#/$defs/user_config", "$defs": _adapters["$defs"]}, format_checker=FormatChecker()
)
# Core schemas never name an add-on or an agent tool (provider agnostic, core works alone). Older core files that
# predate this rule (message, workspaces, addon-manifest's reserved names) are not listed here.
CORE_CLEAN = ["ticket", "run", "run-pending", "needs", "agent-adapter"]
TOOL_NAMES = re.compile(r"scheduler|automation|focus|relay|dashboard|publish|claude|codex", re.I)
# Add-on ext schemas, keyed by ext name. A ticket's ext.<name> is checked with it (as the CLI does for installed add-ons).
EXT = {"automation": V["automation-ext"], "focus": V["focus-ext"]}


SESSION_ARG = re.compile(r"^(\{session\}|--[a-z][a-z0-9-]*=\{session\})$")


def argv_errors(doc):
    """Order rules of agent-adapter.schema.json $defs/argv that JSON Schema cannot express
    (adapters.py checks the same):
    {prompt} is a whole item after a '--' item; {session} is a whole item or --flag={session}."""
    out = []
    for name, a in (doc.get("adapters") or {}).items():
        for mode in ("oneshot", "live"):
            for key, argv in (a.get(mode) or {}).items():
                if not isinstance(argv, list):
                    continue
                for i, item in enumerate(argv):
                    where = f"{name}.{mode}.{key}[{i}]"
                    if "{prompt}" in item and (item != "{prompt}" or "--" not in argv[:i]):
                        out.append(f"{where}: {{prompt}} must be a whole item after '--'")
                    if "{session}" in item and not SESSION_ARG.match(item):
                        out.append(f"{where}: {{session}} must be a whole item or --flag={{session}}")
    return [types.SimpleNamespace(message=m) for m in out]


def errors(kind, doc):
    if kind == "run-event":  # an example file is a list of events (one log)
        if not isinstance(doc, list) or not doc:
            return [types.SimpleNamespace(message="needs a non-empty list of events")]
        return [e for ev in doc for e in V[kind].iter_errors(ev)]
    errs = list(V[kind].iter_errors(doc))
    if kind == "agent-adapter" and not errs:
        errs += argv_errors(doc)
    if kind == "ticket" and isinstance(doc.get("ext"), dict):
        for name, data in doc["ext"].items():
            if name in EXT:
                errs += list(EXT[name].iter_errors(data))
    return errs


def load(f):
    return tomllib.loads(f.read_text()) if f.suffix == ".toml" else json.loads(f.read_text())


def check(kind, doc, want_ok, label):
    errs = errors(kind, doc)
    if bool(errs) == want_ok:
        fails.append(f"{label}: expected {'valid' if want_ok else 'invalid'}, got {errs[0].message if errs else 'valid'}")


for kind in V:
    files = sorted((HERE / "examples" / kind).glob("*.*"))
    for f in files:
        check(kind, load(f), f.name.startswith("valid-"), f"examples/{kind}/{f.name}")
    for prefix in ("valid-", "invalid-"):
        if not any(f.name.startswith(prefix) for f in files):
            fails.append(f"examples/{kind}: needs at least one {prefix}* example")

for name in CORE_CLEAN:
    hit = TOOL_NAMES.search((HERE / f"{name}.schema.json").read_text())
    if hit:
        fails.append(f"{name}.schema.json names an add-on or agent tool: {hit.group(0)!r}")

review = HERE / "review"
check("ticket", json.loads((review / "ticket.example.json").read_text()), True, "review/ticket")
check("workspaces", json.loads((review / "workspaces.example.json").read_text()), True, "review/workspaces")
check("addon-manifest", load(review / "automation.orch-addon.toml"), True, "review/automation.orch-addon")
check("addon-view", load(review / "scheduler.view.example.json"), True, "review/scheduler.view")
for i, m in enumerate(json.loads((review / "message.examples.json").read_text())):
    check("message", m, True, f"review/message[{i}]")


def decrypt(key_b64, blob):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = base64.urlsafe_b64decode(key_b64 + "=" * (-len(key_b64) % 4))
    if blob[:4] != b"OPF1" or len(blob) < 32:
        raise ValueError("bad magic")
    plain = AESGCM(key).decrypt(blob[4:16], blob[16:], b"OPF1")
    (n,) = struct.unpack(">I", plain[:4])
    if not 1 <= n <= 65536:
        raise ValueError("bad header length")
    header = json.loads(plain[4 : 4 + n].decode())
    body = plain[4 + n :]
    if header["size"] != len(body):
        raise ValueError("size mismatch")
    return header, body


vec = json.loads((HERE / "vectors" / "publish-blob-v1.json").read_text())
g = vec["good"]
for gname in ("good", "good_with_note"):
    g = vec[gname]
    try:
        h, body = decrypt(g["key_b64url"], bytes.fromhex(g["blob_hex"]))
        if body.decode() != g["content_utf8"]:
            fails.append(f"vector {gname}: content differs")
        if json.dumps(h, ensure_ascii=False, separators=(",", ":")) != g["header_json"]:
            fails.append(f"vector {gname}: header differs")
    except Exception as e:  # noqa: BLE001
        fails.append(f"vector {gname}: {e!r}")
for case in vec["must_fail"]:
    try:
        decrypt(case["key_b64url"], bytes.fromhex(case["blob_hex"]))
        fails.append(f"vector {case['name']}: decrypted but must fail")
    except Exception:  # noqa: BLE001
        pass


def unbundle(raw):
    """Reader rules of crypto.md "Folder bundle". Returns {path: bytes}."""
    (m,) = struct.unpack(">I", raw[:4])
    if not 1 <= m <= 1 << 20 or 4 + m > len(raw):
        raise ValueError("bad index length")
    idx = json.loads(raw[4 : 4 + m].decode())
    files, out, pos = idx["files"], {}, 4 + m
    if idx.get("v") != 1 or not 1 <= len(files) <= 2000 or not str(idx.get("entry", "")).lower().endswith((".html", ".htm")):
        raise ValueError("bad index")
    for f in files:
        p, n = f["path"], f["size"]
        segs = p.split("/")
        bad = not 1 <= len(p) <= 255 or "\\" in p or "\0" in p or any(x in ("", ".", "..") for x in segs)
        if bad or p in out or not isinstance(n, int) or n < 0:
            raise ValueError("bad path or size: " + p)
        out[p] = raw[pos : pos + n]
        pos += n
    if pos != len(raw) or idx["entry"] not in out:
        raise ValueError("sizes do not add up")
    return out


bvec = json.loads((HERE / "vectors" / "publish-bundle-v1.json").read_text())
for gname in ("good", "good_no_index"):
    try:
        raw = bytes.fromhex(bvec[gname]["bundle_hex"])
        got = unbundle(raw)
        want = {f["path"]: f["content_utf8"].encode() for f in bvec[gname]["files"]}
        (m,) = struct.unpack(">I", raw[:4])
        if got != want or json.loads(raw[4 : 4 + m])["entry"] != bvec[gname]["entry"]:
            fails.append(f"bundle vector {gname}: files or entry differ")
    except Exception as e:  # noqa: BLE001
        fails.append(f"bundle vector {gname}: {e!r}")
for case in bvec["must_fail"]:
    try:
        unbundle(bytes.fromhex(case["bundle_hex"]))
        fails.append(f"bundle vector {case['name']}: unpacked but must fail")
    except Exception:  # noqa: BLE001
        pass

# clean_untrusted (SA-14): reference rules of vectors/clean-untrusted-v1.json;
# workspace/src/orch/text.py must give the same outputs. Order matters: drop invisible characters FIRST
# (so they cannot split a comment marker), then remove comments until nothing changes, then an open "<!--" tail.
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_OPEN_TAIL = re.compile(r"<!--.*\Z", re.S)
# Default_Ignorable_Code_Point (Unicode DerivedCoreProperties), dropped whatever their category.
_DROP = (
    {0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFEFF, 0xFFA0}
    | set(range(0x180B, 0x1810))
    | set(range(0x200B, 0x2010))
    | set(range(0x202A, 0x202F))
    | set(range(0x2060, 0x2070))
    | set(range(0xFE00, 0xFE10))
    | set(range(0xFFF0, 0xFFF9))
    | set(range(0x1BCA0, 0x1BCA4))
    | set(range(0x1D173, 0x1D17B))
    | set(range(0xE0000, 0xE1000))
    | {0x2800}  # braille blank: looks empty, not ignorable
)


def clean_untrusted(text, limit=2000):
    text = unicodedata.normalize("NFC", text).replace("\u2028", "\n").replace("\u2029", "\n")
    text = "".join(
        ch
        for ch in text
        if ch in "\n\t" or (unicodedata.category(ch) not in ("Cc", "Cf", "Cn", "Cs") and ord(ch) not in _DROP)
    )
    while True:
        cut = _COMMENT.sub("", text)
        if cut == text:
            break
        text = cut
    return _OPEN_TAIL.sub("", text)[:limit]


cvec = json.loads((HERE / "vectors" / "clean-untrusted-v1.json").read_text())
if len(cvec["cases"]) < 3:
    fails.append("clean-untrusted vector: needs at least three cases")
for case in cvec["cases"]:
    if clean_untrusted(case["in"]) != case["out"]:
        fails.append(f"clean-untrusted vector {case['name']}: output differs")

# ticket_view (mobile chat): schema + the 16 KB cap on body.ticket_view as compact UTF-8 JSON.
# The relay (relay/tests/ticket_view.rs) and the workspace (workspace/tests/test_ticket_view.py) replay the same cases.
tvec = json.loads((HERE / "vectors" / "ticket-view-v1.json").read_text())
for case in tvec["cases"]:
    m = case["message"]
    view = m["body"].get("ticket_view")
    big = view is not None and len(json.dumps(view, separators=(",", ":"), ensure_ascii=False).encode()) > tvec["cap_bytes"]
    ok = not errors("message", m) and not big
    if ok != case["ok"]:
        fails.append(f"ticket-view vector {case['name']}: expected {'ok' if case['ok'] else 'refused'}")


# Ticket keys: reference rule for the code suggested from a folder name (workspace/src/orch/config.py
# suggest_code gives the same) and the key pattern of ticket.schema.json.
def suggest_code(name):
    """Initials of the words (up to 4); one word gives its first 3 characters. ASCII letters and digits only,
    uppercase; fewer than 2 characters are filled up with W, S (empty name -> WS)."""
    words = re.findall(r"[A-Za-z0-9]+", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode())
    code = ("".join(w[0] for w in words[:4]) if len(words) > 1 else (words[0][:3] if words else "")).upper()
    return (code + "WS")[:2] if len(code) < 2 else code


kvec = json.loads((HERE / "vectors" / "ticket-key-v1.json").read_text())
_ts = json.loads((HERE / "ticket.schema.json").read_text())["$defs"]
_KEY, _CODE = re.compile(_ts["key"]["pattern"]), re.compile(_ts["code"]["pattern"])
for name, want in kvec["suggest"]:
    got = suggest_code(name)
    if got != want or not _CODE.match(got):
        fails.append(f"ticket-key vector suggest {name!r}: got {got!r}, want {want!r}")
for k in kvec["valid_keys"]:
    if not _KEY.match(k):
        fails.append(f"ticket-key vector: {k!r} must be a valid key")
for k in kvec["invalid_keys"]:
    if _KEY.match(k):
        fails.append(f"ticket-key vector: {k!r} must be refused")


# Phone API v3 (relay-api.md, Phone API): request/response bodies in phone-api.schema.json, which points into
# message.schema.json. Every /v1/phone example and the phone-v3 vector are checked against it.
_msg_schema = _expand(json.loads((HERE / "message.schema.json").read_text()))
_phone_schema = json.loads((HERE / "phone-api.schema.json").read_text())
_reg = Registry().with_resources(
    [(s["$id"], Resource.from_contents(s)) for s in (_msg_schema, _phone_schema)]
)


def phone_errors(defname, doc):
    v = Draft202012Validator({"$ref": f"{_phone_schema['$id']}#/$defs/{defname}"}, registry=_reg, format_checker=FormatChecker())
    return list(v.iter_errors(doc))


# (method, path regex, request $def or None, {status: response $def}); error statuses use $defs/error.
PHONE_ROUTES = [
    ("POST", r"/v1/phone/send", "send_request", {201: "send_response", 200: "send_response"}),
    ("POST", r"/v1/phone/answer", "answer_request", {201: "answer_response", 200: "answer_response"}),
    ("POST", r"/v1/phone/blobs", None, {201: "blob_response"}),
    ("GET", r"/v1/phone/messages(\?.*)?", None, {200: "messages_response"}),
    ("GET", r"/v1/phone/workspaces", None, {200: "workspaces_response"}),
    ("PATCH", r"/v1/phone/workspaces/ws_[a-z0-9]{10}", "workspace_patch_request", {200: "workspace_item"}),
    ("GET", r"/v1/phone/settings", None, {200: "settings"}),
    ("PATCH", r"/v1/phone/settings", "settings_patch_request", {200: "settings"}),
    ("POST", r"/v1/phone/invitations/redeem", "redeem_request", {200: "redeem_response"}),
    ("POST", r"/v1/phone/transcribe(\?.*)?", None, {200: "transcribe_response"}),
]
NEW_PHONE_PATHS = ["/v1/phone/blobs", "/v1/phone/speech/", "/v1/phone/settings", "/v1/phone/invitations/redeem"]
_seen_new = set()
for i, ex in enumerate(json.loads((review / "relay-api.examples.json").read_text())):
    req, resp = ex["request"], ex["response"]
    for np in NEW_PHONE_PATHS:
        if req["path"].startswith(np):
            _seen_new.add(np)
    for method, rx, reqdef, respdefs in PHONE_ROUTES:
        if req["method"] != method or not re.fullmatch(rx, req["path"]):
            continue
        label = f"review/relay-api[{i}] {method} {req['path']} {resp['status']}"
        if reqdef and req["body"] is not None:
            for e in phone_errors(reqdef, req["body"])[:1]:
                if resp["status"] < 400 or resp["status"] in (409, 410, 404):
                    fails.append(f"{label}: request: {e.message}")
        if resp["status"] >= 400:
            for e in phone_errors("error", resp["body"])[:1]:
                fails.append(f"{label}: error body: {e.message}")
        elif resp["status"] in respdefs:
            for e in phone_errors(respdefs[resp["status"]], resp["body"])[:1]:
                fails.append(f"{label}: response: {e.message}")
for np in NEW_PHONE_PATHS:
    if np not in _seen_new:
        fails.append(f"review/relay-api: needs an example for {np}")

pvec = json.loads((HERE / "vectors" / "phone-v3-v1.json").read_text())


def build_phone_text(phone, req):
    """Reference: the text message the relay stores for POST /v1/phone/send (without id and created_at)."""
    m = {"schema": "orch.msg/1", "from": phone, "to": req["to"], "type": "text"}
    if req.get("ticket"):
        m["ticket"] = req["ticket"]
    if req.get("reply_to"):
        m["reply_to"] = req["reply_to"]
    body = {"client_id": req["client_id"]}
    if req.get("general") is True:
        body["general"] = True
    for k in ("text", "attachments", "voice", "location", "feedback"):
        if k in req:
            body[k] = req[k]
    m["body"] = body
    return m


for case in pvec["send"]:
    ok = not phone_errors("send_request", case["request"])
    if ok != case["ok"]:
        fails.append(f"phone-v3 vector send {case['name']}: expected {'ok' if case['ok'] else 'refused'}")
    if case["ok"]:
        built = build_phone_text(pvec["phone"], case["request"])
        if built != case.get("built"):
            fails.append(f"phone-v3 vector send {case['name']}: built message differs")
        stored = {**built, "id": "m_0000000000000001", "created_at": "2026-11-06T20:00:00Z"}
        for e in errors("message", stored)[:1]:
            fails.append(f"phone-v3 vector send {case['name']}: built message invalid: {e.message}")
for sect, defname in (("answer", "answer_request"), ("settings_patch", "settings_patch_request"), ("workspace_patch", "workspace_patch_request")):
    for case in pvec[sect]:
        if (not phone_errors(defname, case["request"])) != case["ok"]:
            fails.append(f"phone-v3 vector {sect} {case['name']}: expected {'ok' if case['ok'] else 'refused'}")


def speech_text(body, limit):
    """Reference (relay-api.md, Speech): summary else text; URLs -> 'link'; drop * ` #; one space per whitespace run;
    longer than limit: cut after the last . ! ? that is followed by a space within the limit, else before the last
    space within the limit, else hard at the limit."""
    src = (body.get("speak") or {}).get("summary") or body["text"]
    src = re.sub(r"https?://\S+", "link", src)
    src = re.sub(r"[*`#]", "", src)
    src = re.sub(r"\s+", " ", src).strip()
    if len(src) <= limit:
        return src
    ends = [i for i in range(limit) if src[i] in ".!?" and src[i + 1] == " "]
    if ends:
        return src[: ends[-1] + 1]
    spaces = [i for i in range(limit + 1) if src[i] == " "]
    return src[: spaces[-1]] if spaces else src[:limit]


for case in pvec["speech_text"]:
    got = speech_text(case["body"], pvec["speech_max_chars"])
    if got != case["spoken"]:
        fails.append(f"phone-v3 vector speech_text {case['name']}: got {got!r}")
for case in pvec["general_updates"]:
    if (not errors("message", case["message"])) != case["ok"]:
        fails.append(f"phone-v3 vector general_updates {case['name']}: expected {'ok' if case['ok'] else 'refused'}")
for case in pvec["artifact_ids"]:
    got = "a_" + hashlib.sha256(f"{case['source']}\n{case['ref']}".encode()).hexdigest()[:12]
    if got != case["id"] or not re.fullmatch(_msg_schema["$defs"]["artifact_id"]["pattern"], got):
        fails.append(f"phone-v3 vector artifact_ids {case['ref']}: got {got}")

# Subscriber events and push signatures (relay-api.md, Subscribers).
import hmac as _hmac

_sub_v = validator("subscriber-event")
svec = json.loads((HERE / "vectors" / "subscriber-v1.json").read_text())
for ev in svec["valid_events"]:
    for e in _sub_v.iter_errors(ev):
        fails.append(f"subscriber vector {ev['id']}: {e.message}")
for case in svec["invalid_events"]:
    if not list(_sub_v.iter_errors(case["event"])):
        fails.append(f"subscriber vector invalid {case['name']}: accepted")
for case in svec["signatures"]:
    mac = _hmac.new(case["secret"].encode(), f"{case['timestamp']}.{case['body']}".encode(), hashlib.sha256).hexdigest()
    if "v1=" + mac != case["signature"]:
        fails.append(f"subscriber vector signature {case['name']}: got v1={mac}")

if fails:
    print("\n".join("FAIL " + f for f in fails))
    sys.exit(1)
print("contracts: ALL OK")
