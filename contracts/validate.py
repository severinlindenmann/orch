"""Check every contract example (tickets incl. ext.scheduler, run records, pending input, Needs you rows,
agent adapters and their config entries, messages, workspaces, add-on manifests and views) and the publish
crypto vectors. Every examples/<kind>/ folder needs at least one valid-* and one invalid-* file.

Run: uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py
"""
import base64
import json
import re
import struct
import sys
import tomllib
import types
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

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
EXT = {"scheduler": validator("addons/scheduler.ext"), "automation": V["automation-ext"]}


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
check("addon-manifest", load(review / "scheduler.orch-addon.toml"), True, "review/scheduler.orch-addon")
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
try:
    h, body = decrypt(g["key_b64url"], bytes.fromhex(g["blob_hex"]))
    if body.decode() != g["content_utf8"]:
        fails.append("vector good: content differs")
except Exception as e:  # noqa: BLE001
    fails.append(f"vector good: {e!r}")
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
# workspace/src/orch/text.py must give the same outputs. Order matters: drop invisible characters FIRST (so they
# cannot split a comment marker), then remove comments until nothing changes, then an unterminated "<!--" tail.
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_OPEN_TAIL = re.compile(r"<!--.*\Z", re.S)
_DROP = (
    set(range(0xE0000, 0xE0080))  # tag characters
    | set(range(0xE0100, 0xE01F0))  # variation selectors supplement
    | set(range(0xFE00, 0xFE10))  # variation selectors
    | {0x2800, 0x034F, 0x3164, 0x115F, 0x1160, 0xFEFF, 0xFFA0}
)


def clean_untrusted(text, limit=2000):
    text = unicodedata.normalize("NFC", text).replace("\u2028", "\n").replace("\u2029", "\n")
    text = "".join(
        ch
        for ch in text
        if ch in "\n\t" or (unicodedata.category(ch) not in ("Cc", "Cf") and ord(ch) not in _DROP)
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

if fails:
    print("\n".join("FAIL " + f for f in fails))
    sys.exit(1)
print("contracts: ALL OK")
