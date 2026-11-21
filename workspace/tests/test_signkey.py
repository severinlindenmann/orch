"""ORCH-1200: each workspace makes its own Ed25519 key pair at relay connect, shows its fingerprint, keeps
the private key only in the guarded orch home (never in any output) and registers the public key."""

import base64
import json
import os
import stat
from pathlib import Path

import pytest
from fakes import WS

from orch import secretscan, signkey

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "vectors" / "signing-key-v1.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture
def signkey_home(proj, monkeypatch):
    """A usable guarded orch home for the proj workspace (pairing rules: test_secret_store.py)."""
    from orch import home as orch_home
    from orch import winacl

    h = proj.parent / f"{proj.name}_signkey_home"
    h.mkdir(mode=0o700)
    winacl.allow_home(h)
    monkeypatch.setattr(orch_home, "guarded_home", lambda root: h)
    return h


def _connect(run, rel):
    return run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)


def _key_file(home):
    files = list(home.glob("keys/*/signing.key"))
    assert len(files) == 1, files
    return files[0]


def _forms(home) -> list[str]:
    """The private key in every text form it could leak in."""
    stored = _key_file(home).read_text().strip()
    seed = base64.urlsafe_b64decode(stored[len("ors_") :] + "=")
    return [stored, signkey.b64url(seed), base64.b64encode(seed).decode(), seed.hex()]


def _assert_nowhere(texts, forms):
    for t in texts:
        for f in forms:
            assert f not in t


# ---------------------------------------- shared vectors


@pytest.mark.parametrize("g", VECTORS["good"], ids=lambda g: g["name"])
def test_vectors_good(g):
    raw = signkey.parse_public(g["public_key"])
    assert signkey.key_id(raw) == g["key_id"]
    assert signkey.fingerprint(raw) == g["fingerprint"]


@pytest.mark.parametrize("b", VECTORS["bad"], ids=lambda b: b["name"])
def test_vectors_bad_refused(b):
    with pytest.raises(signkey.Refused):
        signkey.parse_public(b["public_key"])


def test_fingerprint_shape():
    fp = signkey.fingerprint(bytes(32))
    groups = fp.split(" ")
    assert len(groups) == 8 and all(len(g) == 4 for g in groups)
    assert not set(fp.replace(" ", "")) & set("ILOU")  # Crockford: no look-alikes


# ---------------------------------------- made at connect, registered, shown


def test_connect_makes_key_registers_and_shows_fingerprint(proj, run, rel, signkey_home):
    code, out, err = _connect(run, rel)
    assert code == 0, err
    f = _key_file(signkey_home)
    if os.name == "posix":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert signkey.STORED_RE.fullmatch(f.read_text().strip())
    raw = signkey.public_key(proj)
    assert rel.sign_key == signkey.b64url(raw)  # the test relay stores the public key
    fp = signkey.fingerprint(raw)
    assert f"Fingerprint: {fp}" in out
    # shown again later, from this computer's own key
    for argv in (("relay", "key"), ("relay", "status"), ("relay", "whoami")):
        code, o, e = run(*argv)
        assert code == 0, e
        assert fp in o, argv
    code, o, _ = run("relay", "key", "--json")
    shown = json.loads(o)
    assert shown["fingerprint"] == fp and shown["state"] == "unchanged" and shown["made"] is False
    assert json.loads(run("relay", "whoami", "--json")[1])["fingerprint"] == fp


def test_private_key_never_in_output_workspace_or_relay(proj, run, rel, signkey_home):
    outs = list(_connect(run, rel)[1:])
    for argv in (
        ("relay", "key"),
        ("relay", "key", "--json"),
        ("relay", "status", "--json"),
        ("relay", "whoami", "--json"),
    ):
        outs += list(run(*argv)[1:])
    forms = _forms(signkey_home)
    _assert_nowhere(outs, forms)
    # never in a request to the relay
    _assert_nowhere([b.decode("utf-8", "replace") + json.dumps(h) for _, _, h, b in rel.calls], forms)
    # never in the workspace folder
    for p in proj.rglob("*"):
        if p.is_file() and not p.is_symlink():
            _assert_nowhere([p.read_bytes().decode("utf-8", "replace")], forms)


def test_key_made_once_and_kept(proj, run, rel, signkey_home):
    _connect(run, rel)
    first = _key_file(signkey_home).read_text()
    _connect(run, rel)
    assert _key_file(signkey_home).read_text() == first
    assert signkey.ensure(proj)[1] is False


def test_already_connected_workspace_gets_its_key_once(proj, run, rel, signkey_home, monkeypatch):
    # connected before signing keys existed: no key, nothing registered
    with monkeypatch.context() as m:
        m.setattr(signkey, "register", lambda root: (_ for _ in ()).throw(signkey.Refused("old orch")))
        _connect(run, rel)
    assert not list(signkey_home.glob("keys/*/signing.key")) and rel.sign_key is None
    code, out, err = run("relay", "outbox")  # a command without the once-step: still nothing
    assert rel.sign_key is None
    code, out, err = run("relay", "inbox")
    assert code == 0
    assert rel.sign_key == signkey.b64url(signkey.public_key(proj))
    assert "Signing key ready" in err
    puts = [c for c in rel.calls if c[0] == "PUT"]
    run("relay", "inbox")
    assert [c for c in rel.calls if c[0] == "PUT"] == puts  # once: no second registration


def test_relay_holding_another_key_is_said_plainly(proj, run, rel, signkey_home):
    rel.sign_key = "A" * 43
    code, out, err = _connect(run, rel)
    assert code == 0, err
    assert "already holds a different signing key" in out
    assert rel.sign_key == "A" * 43
    n = len(rel.calls)
    run("relay", "inbox")
    assert not [c for c in rel.calls[n:] if c[0] == "PUT"]  # settled: not retried on every command


def test_older_relay_without_the_route_still_connects(proj, run, rel, signkey_home):
    rel.routes = [r for r in rel.routes if r[1] != "/v1/me/signing-key"]
    code, out, err = _connect(run, rel)
    assert code == 0, err
    assert "cannot store it yet" in out
    assert _key_file(signkey_home).is_file()


def test_sign_bytes_verifies_with_the_public_key(proj, run, rel, signkey_home):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    _connect(run, rel)
    sig = signkey.sign_bytes(proj, b"orch-sig-v1\x00msg\x00{}")
    Ed25519PublicKey.from_public_bytes(signkey.public_key(proj)).verify(sig, b"orch-sig-v1\x00msg\x00{}")


def test_loose_key_file_is_refused_not_used(proj, run, rel, signkey_home):
    if os.name != "posix":
        pytest.skip("POSIX rights")
    _connect(run, rel)
    f = _key_file(signkey_home)
    f.chmod(0o644)
    with pytest.raises(signkey.Refused, match="wrong rights"):
        signkey.public_key(proj)
    assert run("relay", "status")[0] == 0  # status still answers, just without a fingerprint


# ---------------------------------------- the secret scan covers it


def test_secret_scan_catches_the_private_key(proj, run, rel, signkey_home):
    _connect(run, rel)
    forms = _forms(signkey_home)
    # the stored form is caught by pattern anywhere, even without this workspace's keys
    assert any(x["kind"] == "orch-token" for x in secretscan.find(f"key: {forms[0]}"))
    # every text form of the seed is caught as this workspace's stored key
    for form in forms:
        kinds = {x["kind"] for x in secretscan.find(f"here it is {form} ok", proj)}
        assert kinds & {"stored-key", "orch-token", "secret-value", "api-token"}, form
    # and refused on the way out to the relay
    code, out, err = run("relay", "send", "ws_reports001", f"look {forms[3]}")
    assert code == 2 and not [m for m in rel.sent if forms[3] in json.dumps(m)]


def test_guard_failure_is_not_read_as_no_key(proj, run, rel, signkey_home, monkeypatch):
    from orch import home as orch_home

    _connect(run, rel)

    def refuse(root):
        raise orch_home.HomeRefused("does not pair")

    monkeypatch.setattr(orch_home, "guarded_home", refuse)
    with pytest.raises(signkey.Refused):
        signkey.needles(proj)  # the hider fails closed, never "nothing to hide"


def test_no_key_folder_yet_means_no_key(proj, signkey_home):
    assert signkey.public_key(proj) is None and signkey.needles(proj) == {}
