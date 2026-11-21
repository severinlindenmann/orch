"""This workspace's own signing key (ORCH-1027 design note section 2, ORCH-1200).

Each workspace makes one Ed25519 key pair, on `orch relay connect` or once on the next relay command of a
workspace that was connected before. The private key lives only in the guarded orch home
(`keys/<workspace>/signing.key`, 0600, the rights rule of home.py); it is never printed, sent, synced, put in
the workspace folder or in a problem report. The secret scan knows its stored form (`ors_` + 43 characters,
secretscan.py) and the value hider knows its value in every text form (keystore.all_needles), so it cannot
leave in a message, a publish or a helper's output by mistake.

The public half (raw 32 bytes, base64url without padding) is registered with the relay
(`PUT /v1/me/signing-key`, relay-api.md). People compare the fingerprint, never the key id:

- key id: first 16 hex characters of SHA-256("ed25519" + raw key), an index only.
- fingerprint: the same hash in Crockford base32, the first 32 characters as 8 groups of 4.

Signing and checking messages are not here (sibling tickets); `sign_bytes` is the one place that reads the
private key, so no caller ever holds it.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import re
from pathlib import Path

from orch.errors import Refused

ALG = "ed25519"
FILE = "signing.key"
REGISTERED = "signing-registered.json"
PREFIX = "ors_"  # the stored form: ors_<base64url of the 32-byte seed, no padding>
STORED_RE = re.compile(r"ors_[A-Za-z0-9_-]{43}")
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


# ---------------------------------------- public key forms (no secret)


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _digest(raw: bytes) -> bytes:
    return hashlib.sha256(ALG.encode("ascii") + raw).digest()


def key_id(raw: bytes) -> str:
    """An index for a public key; trust is always the full key."""
    return _digest(raw).hex()[:16]


def fingerprint(raw: bytes) -> str:
    """What a person compares: 8 groups of 4 Crockford base32 characters (160 bits)."""
    n = int.from_bytes(_digest(raw), "big")
    bits = 256
    chars = []
    for i in range(32):
        shift = bits - 5 * (i + 1)
        chars.append(CROCKFORD[(n >> shift) & 31])
    s = "".join(chars)
    return " ".join(s[i : i + 4] for i in range(0, 32, 4))


# Ed25519 point checks for a public key that came from outside (the relay, a contact): exactly 32 bytes, the
# one canonical encoding of a point on the curve, and not of small order (the 8 torsion points). The same
# rules as the relay (signkeys.rs, ed25519-dalek is_weak) and the design note.
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _decode_point(raw: bytes) -> tuple[int, int] | None:
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None  # not canonical
    u = (y * y - 1) % _P
    v = (_D * y * y + 1) % _P
    x = (u * pow(v, 3, _P) * pow(u * pow(v, 7, _P), (_P - 5) // 8, _P)) % _P
    if (v * x * x - u) % _P != 0:
        x = (x * _SQRT_M1) % _P
        if (v * x * x - u) % _P != 0:
            return None  # not on the curve
    if x == 0 and sign:
        return None  # "-0": a second spelling of the same point
    if (x & 1) != sign:
        x = _P - x
    return x, y


def _double(pt: tuple[int, int]) -> tuple[int, int]:
    x, y = pt
    den_x = (1 + _D * x * x * y * y) % _P
    den_y = (1 - _D * x * x * y * y) % _P
    nx = (2 * x * y * pow(den_x, _P - 2, _P)) % _P
    ny = ((y * y + x * x) * pow(den_y, _P - 2, _P)) % _P
    return nx, ny


def public_problem(raw: bytes) -> str | None:
    """Why a public key from outside is refused (plain words), or None when it is a usable Ed25519 key."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 32:
        return "The key is not 32 bytes long."
    pt = _decode_point(bytes(raw))
    if pt is None:
        return "The key is not a valid Ed25519 key."
    for _ in range(3):  # 8 * P is the neutral point exactly when P has small order
        pt = _double(pt)
    if pt == (0, 1):
        return "The key is a weak (small-order) key."
    return None


def parse_public(text: str) -> bytes:
    """Raw key from its wire form (base64url, no padding, one spelling), or Refused."""
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", text):
        raise Refused("The key is not written as 43 base64url characters.")
    raw = base64.urlsafe_b64decode(text + "=")
    if b64url(raw) != text:
        raise Refused("The key is not written the one canonical way.")
    why = public_problem(raw)
    if why:
        raise Refused(why)
    return raw


# ---------------------------------------- the private key (guarded orch home only)


def _key_file(root: Path, create: bool) -> Path:
    from orch import home as orch_home

    return orch_home.key_dir(root, create=create) / FILE


def _load_private(root: Path):
    """The private key object, or None when there is none yet. A loose or damaged file is Refused, never
    trusted and never replaced by itself (a person runs orch doctor)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from orch import addons
    from orch import home as orch_home

    # Only "this folder has no key folder yet" means no key. Every other refusal (a home that does not pair,
    # wrong rights, a link) is raised, so the value hider fails closed instead of hiding nothing.
    if addons.workspace_id(root, create=False) is None:
        return None
    home = orch_home.guarded_home(root)
    if not (home / "keys").is_dir():
        return None
    f = _key_file(root, create=False)
    try:
        raw = orch_home._read_guarded(f)
    except FileNotFoundError:
        return None
    except orch_home.LooseFile:
        raise Refused("This workspace's signing key has the wrong rights. Fix: orch doctor") from None
    text = raw.decode("ascii", "replace").strip()
    if not STORED_RE.fullmatch(text):
        raise Refused("This workspace's signing key is damaged.")
    seed = base64.urlsafe_b64decode(text[len(PREFIX) :] + "=")
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_raw(priv) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def ensure(root: Path) -> tuple[bytes, bool]:
    """(raw public key, made now). Makes the pair once under the key folder's lock; keeps an existing one."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    from orch import home as orch_home

    d = orch_home.key_dir(root, create=True)
    with orch_home._key_lock(d):
        priv = _load_private(root)
        if priv is not None:
            return _public_raw(priv), False
        priv = Ed25519PrivateKey.generate()
        seed = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        orch_home._write_private(d / FILE, PREFIX + b64url(seed) + "\n")
        del seed
        return _public_raw(priv), True


def public_key(root: Path) -> bytes | None:
    """This workspace's raw public key, or None when it has none yet. Never makes one."""
    priv = _load_private(root)
    return None if priv is None else _public_raw(priv)


def sign_bytes(root: Path, data: bytes) -> bytes:
    """The Ed25519 signature of `data` with this workspace's key (for the signing tickets)."""
    priv = _load_private(root)
    if priv is None:
        raise Refused("This workspace has no signing key yet. Run: orch relay key")
    return priv.sign(bytes(data))


def needles(root: Path) -> dict[str, list[str]]:
    """The private key in every text form it could show up in, for the value hider (keystore.all_needles).
    {} when there is none. A key that cannot be read raises, so the hider fails closed."""
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    priv = _load_private(root)
    if priv is None:
        return {}
    seed = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return {
        "orch-signing-key": [
            PREFIX + b64url(seed),
            b64url(seed),
            base64.b64encode(seed).decode("ascii"),
            seed.hex(),
        ]
    }


# ---------------------------------------- registering with the relay


def info(raw: bytes) -> dict:
    return {"alg": ALG, "public_key": b64url(raw), "key_id": key_id(raw), "fingerprint": fingerprint(raw)}


def _registered(root: Path) -> dict | None:
    import json

    from orch import home as orch_home

    try:
        d = orch_home.key_dir(root, create=False)
        return json.loads(orch_home._read_guarded(d / REGISTERED))
    except (Refused, OSError, ValueError):
        return None


def _note_registered(root: Path, url: str, workspace: str, kid: str, state: str) -> None:
    import json

    from orch import home as orch_home

    d = orch_home.key_dir(root, create=True)
    with orch_home._key_lock(d):
        orch_home._write_private(
            d / REGISTERED,
            json.dumps({"url": url, "workspace": workspace, "key_id": kid, "state": state}),
        )


def register(root: Path) -> dict:
    """Make the pair if needed and register its public half with the connected relay. Returns
    {state, made, alg, public_key, key_id, fingerprint}; state is stored, unchanged, other_key (the relay
    holds a different key for this workspace) or not_supported (an older relay)."""
    from orch import net

    cfg = net.load_service(root, "relay")
    raw, made = ensure(root)
    body = {"alg": ALG, "public_key": b64url(raw)}
    out = {**info(raw), "made": made}
    from orch import relay  # the one way out: its body is scanned like every relay call (R5.2)

    try:
        status, resp = relay._api(root, "PUT", "/v1/me/signing-key", body, timeout=30)
    except Refused as e:
        code = getattr(e, "status", None)
        if code == 404:
            return {**out, "state": "not_supported"}
        if code == 409:
            _note_registered(root, cfg["url"], cfg["workspace"], out["key_id"], "other_key")
            return {**out, "state": "other_key"}
        raise
    if not isinstance(resp, dict) or resp.get("public_key") != body["public_key"]:
        raise Refused("The relay answered with a different key. Nothing was changed here.")
    state = "stored" if status == 201 else "unchanged"
    _note_registered(root, cfg["url"], cfg["workspace"], out["key_id"], "registered")
    return {**out, "state": state}


def needs_register(root: Path) -> bool:
    """True when connected and the key is not yet registered with that relay (no network)."""
    from orch import net

    try:
        cfg = net.load_service(root, "relay")
    except Refused:
        return False
    r = _registered(root)
    if not isinstance(r, dict) or r.get("state") not in ("registered", "other_key"):
        return True  # other_key is settled too: it is shown by `orch relay key`, not on every command
    try:
        raw = public_key(root)
    except Refused:
        return False  # a damaged key is shown by `orch relay key`, never replaced here
    return (
        raw is None
        or r.get("url") != cfg.get("url")
        or r.get("workspace") != cfg.get("workspace")
        or (r.get("key_id") != key_id(raw))
    )


def register_quietly(root: Path) -> str | None:
    """The once-for-already-connected-workspaces step before relay commands: register when needed, never stop
    the command. A plain line to show, or None."""
    if not needs_register(root):
        return None
    with contextlib.suppress(Refused, OSError, ValueError, TimeoutError):
        r = register(root)
        return line(r)
    return None


def line(r: dict) -> str:
    """One plain line about the result of register()."""
    fp = r["fingerprint"]
    if r["state"] in ("stored", "unchanged"):
        return f"Signing key ready. Fingerprint: {fp}"
    if r["state"] == "other_key":
        return (
            f"The relay already holds a different signing key for this workspace, so this one ({fp}) "
            "was not stored. Ask the relay admin."
        )
    return f"Signing key made ({fp}). This relay cannot store it yet."
