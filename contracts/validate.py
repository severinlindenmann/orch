"""Check every contract example and the publish crypto vector.

Run: uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py
"""
import base64
import json
import re
import struct
import sys
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


V = {"ticket": validator("ticket"), "message": validator("message"), "workspaces": validator("workspaces")}


def check(kind, doc, want_ok, label):
    errs = list(V[kind].iter_errors(doc))
    if bool(errs) == want_ok:
        fails.append(f"{label}: expected {'valid' if want_ok else 'invalid'}, got {errs[0].message if errs else 'valid'}")


for kind in V:
    for f in sorted((HERE / "examples" / kind).glob("*.json")):
        check(kind, json.loads(f.read_text()), f.name.startswith("valid-"), f"examples/{kind}/{f.name}")

review = HERE / "review"
check("ticket", json.loads((review / "ticket.example.json").read_text()), True, "review/ticket")
check("workspaces", json.loads((review / "workspaces.example.json").read_text()), True, "review/workspaces")
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

if fails:
    print("\n".join("FAIL " + f for f in fails))
    sys.exit(1)
print("contracts: ALL OK")
