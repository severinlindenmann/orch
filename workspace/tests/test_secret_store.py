"""The key store in the guarded orch home (slice 1.1): rights, atomic writes, the local-id binding, the home
pairing, no key values in messages, and the relay refresh writing there. Every test lives under a temp account
home (the getpwuid home is monkeypatched), with its test workspace under <account>/.orch-test; the real
account home and ~/.orch-tool are never touched (the session guard in conftest checks the latter)."""

import contextlib
import json
import os
import shutil
import stat
from pathlib import Path

import pytest
from conftest import seed_profiles, turn_on
from fakes import WS

from orch import addons, keystore
from orch import humanproof as hp
from orch.errors import Refused

TOKEN = "tok-Q7xP2mK9vL4zR8"  # a made-up value, long enough to be stored
TOKEN2 = "tok-W3nB6cF1yH5qD0"
posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX modes")


@pytest.fixture
def acct(tmp_path, monkeypatch):
    a = tmp_path / "acct"
    (a / ".orch-test").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: a)
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    monkeypatch.delenv("ORCH_HOME", raising=False)
    return a


@pytest.fixture
def tws(acct, monkeypatch):
    """A test workspace with its test home (ORCH_HOME), both under <account>/.orch-test."""
    base = acct / ".orch-test"
    ws = base / "ws"
    (ws / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    return ws


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.lstat().st_mode)


def _tree_text(root: Path) -> str:
    """Every file under root, as text, for 'no key value anywhere' checks."""
    out = []
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            out.append(p.read_bytes().decode("utf-8", "replace"))
    return "\n".join(out)


# ------------------------------------------------------------------------------ create, read, list


def test_create_read_list_and_remove(tws):
    keystore.add(tws, "databricks-token", "token", TOKEN)
    keystore.add(tws, "pw", "password", "correct horse")
    keystore.add(tws, "google-sa.json", "json", '{"type": "service_account", "k": "abcdefghij"}')
    keystore.add(tws, "deploy-key", "key-file", b"-----BEGIN KEY-----\n\x00\x01binary\n")
    assert keystore.get_value(tws, "databricks-token") == TOKEN
    assert keystore.get_value(tws, "deploy-key") == b"-----BEGIN KEY-----\n\x00\x01binary\n"
    items = keystore.list_keys(tws)
    assert [(i["name"], i["type"], i["source"]) for i in items] == [
        ("databricks-token", "token", "workspace"),
        ("deploy-key", "key-file", "workspace"),
        ("google-sa.json", "json", "workspace"),
        ("pw", "password", "workspace"),
    ]
    assert TOKEN not in json.dumps(items)
    keystore.remove(tws, "deploy-key")
    assert not (hp.key_dir(tws) / "files" / "deploy-key").exists()
    with pytest.raises(Refused, match="no such key"):
        keystore.get_value(tws, "deploy-key")


def test_keys_file_matches_the_contract_schema(tws):
    jsonschema = pytest.importorskip("jsonschema")
    keystore.add(tws, "a-token", "token", TOKEN)
    keystore.add(tws, "kf", "key-file", b"filebytes")
    keystore.set_admin(tws, {"adm": TOKEN2, "sa": {"type": "service_account", "k": "abcdefghij"}})
    schema = json.loads((Path(__file__).parents[2] / "contracts" / "secrets.schema.json").read_text())
    for f in ("keys.json", "admin-keys.json"):
        doc = json.loads((hp.key_dir(tws) / f).read_text())
        jsonschema.validate(doc, {"$ref": "#/$defs/keys_file", "$defs": schema["$defs"]})


@pytest.mark.parametrize(
    "type_,value,msg",
    [
        ("token", "short", "too short"),
        ("password", "1234567", "too short"),
        ("token", "line one\nline two", "one line"),
        ("json", "not json at all", "JSON object"),
        ("json", "[1, 2, 3, 4, 5, 6]", "JSON object"),
        ("key-file", b"", "needs its content"),
        ("key-file", b"x" * (1024 * 1024 + 1), "at most 1 MB"),
        ("ssh", "whatever-value", "Unknown key type"),
    ],
)
def test_values_the_store_refuses(tws, type_, value, msg):
    with pytest.raises(Refused, match=msg):
        keystore.add(tws, "k", type_, value)
    assert keystore.list_keys(tws) == []


@pytest.mark.parametrize("name", ["", ".hidden", "a/b", "../x", "a b", "x" * 65, "-x"])
def test_bad_names_are_refused(tws, name):
    with pytest.raises(Refused, match="key name"):
        keystore.add(tws, name, "token", TOKEN)


def test_admin_keys_are_read_only_and_a_workspace_key_shadows_the_admin_one(tws):
    keystore.add(tws, "mine", "token", TOKEN)
    skipped = keystore.set_admin(tws, {"mine": TOKEN2, "theirs": TOKEN2, "tiny": "abc"})
    assert keystore.get_value(tws, "mine") == TOKEN  # the workspace key is used
    assert keystore.get_value(tws, "theirs") == TOKEN2
    assert [s.split(":")[0] for s in skipped] == ["key tiny"] and "too short" in skipped[0]
    assert [(i["name"], i["source"], i["state"]) for i in keystore.list_keys(tws)] == [
        ("mine", "workspace", "active"),
        ("mine", "admin", "shadowed"),
        ("theirs", "admin", "active"),
    ]
    with pytest.raises(Refused, match="managed by your admin"):
        keystore.remove(tws, "theirs")
    keystore.remove(tws, "mine")  # the admin key is active again
    assert keystore.get_value(tws, "mine") == TOKEN2
    assert [i["state"] for i in keystore.list_keys(tws)] == ["active", "active"]
    keystore.add(tws, "theirs", "token", TOKEN)  # a person may shadow an admin key
    assert keystore.get_value(tws, "theirs") == TOKEN
    keystore.set_admin(tws, {})  # the admin took everything back: workspace keys stay
    assert [i["name"] for i in keystore.list_keys(tws)] == ["theirs"]


def test_a_type_change_leaves_no_stale_key_file(tws):
    keystore.add(tws, "k", "key-file", b"filebytes")
    keystore.add(tws, "k", "token", TOKEN)
    assert not (hp.key_dir(tws) / "files" / "k").exists()


def test_records_are_an_allowlist(tws):
    for bad in ("delivered", "proofs-used", "human-settings", "proposals", "keys", "admin-keys"):
        with pytest.raises(Refused):
            keystore.record_write(tws, bad, {})
    keystore.record_write(tws, "dev", {"a": 1})


def test_every_key_store_write_sets_the_windows_rights_before_the_secret(tws, monkeypatch):
    """Simulated Windows: winacl.set_private is called for each temp file before it is written (keys.json,
    admin-keys.json, a key file, profiles.toml, a record, the binding)."""
    from orch import winacl

    calls = []
    real_write = os.fdopen

    def spy(path, is_dir):
        p = Path(path)
        calls.append((p.name, is_dir, p.stat().st_size if p.exists() else None))

    monkeypatch.setattr(winacl, "set_private", spy)
    keystore.add(tws, "k", "token", TOKEN)
    keystore.add(tws, "kf", "key-file", b"filebytes")
    keystore.set_admin(tws, {"adm": TOKEN2})
    seed_profiles(tws, {"p": {"env": {"A": "k"}}})
    keystore.record_write(tws, "dev", {"a": 1})
    assert real_write
    temps = [c for c in calls if c[0].endswith(".tmp") and not c[1]]
    assert temps and all(size == 0 for _, _, size in temps)  # always before the first byte
    seen = " ".join(n for n, _, _ in temps)
    for part in ("keys.json", "admin-keys.json", "kf", "profiles.toml", "dev.json", "binding"):
        assert part in seen, part


@posix_only
def test_a_set_aside_file_keeps_names_only_and_the_original_is_gone(tws):
    keystore.add(tws, "k1", "token", SENTINEL)
    keystore.add(tws, "kf", "key-file", SENTINEL.encode())
    d = hp.key_dir(tws)
    os.chmod(d / "files" / "kf", 0o644)
    keystore.list_keys(tws)
    os.chmod(d / "keys.json", 0o644)
    keystore.list_keys(tws)
    for p in [*d.glob("keys.json*"), *(d / "files").glob("kf*")]:
        assert SENTINEL not in p.read_text(errors="replace"), p
        if ".loose-" in p.name:
            assert _mode(p) == 0o600
    assert not (d / "keys.json").exists() and not (d / "files" / "kf").exists()
    assert {i["name"] for i in keystore.list_keys(tws)} == {"k1", "kf"}


def test_preflight_with_empty_credentials_still_refuses_a_bad_key_store(tws, monkeypatch):
    relay = _refresh_fixture(tws, monkeypatch)
    keystore.add(tws, "mine", "token", TOKEN)
    hp._write_private(hp.key_dir(tws) / "keys.json", "{broken")
    snap = relay._api(None, None, None)[1]
    snap["credentials"] = {}
    with pytest.raises(Refused, match="damaged"):
        relay.refresh(tws)
    _nothing_replaced(tws)


# ------------------------------------------------------------------------------ profiles


PROFILES = {
    "databricks": {
        "env": {"DATABRICKS_TOKEN": "databricks-token"},
        "set": {"DATABRICKS_HOST": "https://adb-1234.azuredatabricks.net"},
        "run": ["databricks"],
        "skills": ["databricks-jobs"],
    },
    "google": {"files": {"GOOGLE_APPLICATION_CREDENTIALS": "google-sa.json"}, "allow_get": True},
}


def test_profiles_round_trip_names_only(tws):
    assert keystore.read_profiles(tws) == {}
    keystore.add(tws, "databricks-token", "token", TOKEN)
    seed_profiles(tws, PROFILES)
    assert keystore.read_profiles(tws) == PROFILES
    text = (hp.key_dir(tws) / "profiles.toml").read_text()
    assert TOKEN not in text and 'schema = "orch.secret-profiles/1"' in text


def test_profiles_never_hold_a_key_value_or_a_loader_variable(tws):
    keystore.add(tws, "databricks-token", "token", TOKEN)
    with pytest.raises(Refused, match="holds a key value") as e:
        seed_profiles(tws, {"p": {"env": {"X_TOKEN": "databricks-token"}, "set": {"X_HOST": TOKEN}}})
    assert TOKEN not in str(e.value)
    for var in ("PATH", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "GIT_SSH_COMMAND", "ORCH_HOME", "HTTPS_PROXY"):
        with pytest.raises(Refused, match="may not set"):
            seed_profiles(tws, {"p": {"env": {var: "databricks-token"}}})
    with pytest.raises(Refused, match="at least one key"):
        seed_profiles(tws, {"p": {"set": {"X_HOST": "h"}}})
    with pytest.raises(Refused, match="does not know"):
        seed_profiles(tws, {"p": {"env": {"A": "k"}, "value": TOKEN}})
    assert not (hp.key_dir(tws) / "profiles.toml").exists()


def test_a_planted_profile_file_with_a_loader_variable_is_refused_on_read(tws):
    d = hp.key_dir(tws)
    hp._write_private(
        d / "profiles.toml",
        'schema = "orch.secret-profiles/1"\n[profile.p]\nenv = { LD_PRELOAD = "k1" }\n',
    )
    with pytest.raises(Refused, match="may not set"):
        keystore.read_profiles(tws)
    hp._write_private(d / "profiles.toml", "this is [not toml")
    with pytest.raises(Refused, match="damaged"):
        keystore.read_profiles(tws)


# ------------------------------------------------------------------------------ records


def test_records_round_trip_and_reserved_names(tws):
    assert keystore.record_read(tws, "relay") is None
    keystore.record_write(tws, "relay", {"url": "http://r", "workspace": "ws_a", "token": "orn_" + TOKEN})
    assert keystore.record_read(tws, "relay")["workspace"] == "ws_a"
    for bad in ("keys", "profiles", "binding", "human", "../x", "Relay", "other"):
        with pytest.raises(Refused):
            keystore.record_write(tws, bad, {})


# ------------------------------------------------------------------------------ rights


@posix_only
def test_folders_are_0700_and_files_0600(tws):
    keystore.add(tws, "k", "token", TOKEN)
    keystore.add(tws, "f", "key-file", b"filebytes")
    seed_profiles(tws, {"p": {"env": {"A": "k"}}})
    d = hp.key_dir(tws)
    for p in (d, d / "files", d.parent):
        assert _mode(p) == 0o700, p
    for p in ("keys.json", "profiles.toml", "binding.json", "files/f"):
        assert _mode(d / p) == 0o600, p
    assert not list(d.rglob("*.tmp"))  # no temp file stays behind


@posix_only
def test_a_loose_folder_is_tightened_and_a_link_refuses_every_read(tws):
    keystore.add(tws, "k", "token", TOKEN)
    d = hp.key_dir(tws)
    os.chmod(d, 0o755)
    assert [i["name"] for i in keystore.list_keys(tws)] == ["k"]  # folders may be tightened
    assert _mode(d) == 0o700
    real = d / "keys.json"
    moved = d / "keys.real"
    real.rename(moved)
    real.symlink_to(moved)  # a link in place of the file
    with pytest.raises(Refused, match="wrong rights"):
        keystore.get_value(tws, "k")


# ------------------------------------------------------------------------------ atomicity


@contextlib.contextmanager
def _failing_replace(monkeypatch, only_name: str):
    real = os.replace

    def rep(src, dst, *a, **k):
        if Path(dst).name == only_name:
            raise OSError("disk full")
        return real(src, dst, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(os, "replace", rep)
        yield


def test_a_failed_add_keeps_the_old_state(tws, monkeypatch):
    keystore.add(tws, "k", "token", TOKEN)
    keystore.add(tws, "f", "key-file", b"old file bytes")
    d = hp.key_dir(tws)
    before = (d / "keys.json").read_bytes()
    with _failing_replace(monkeypatch, "keys.json"):
        with pytest.raises(OSError):
            keystore.add(tws, "k", "token", TOKEN2)
        with pytest.raises(OSError):
            keystore.add(tws, "f", "key-file", b"new file bytes")
        with pytest.raises(OSError):
            keystore.add(tws, "g", "key-file", b"brand new")
    assert (d / "keys.json").read_bytes() == before
    assert keystore.get_value(tws, "k") == TOKEN
    assert keystore.get_value(tws, "f") == b"old file bytes"  # the file is rolled back too
    assert not (d / "files" / "g").exists()
    assert not list(d.rglob("*.tmp")) and not (d / "keys.lock").exists()


def test_an_interrupted_admin_write_keeps_the_old_admin_keys(tws, monkeypatch):
    keystore.set_admin(tws, {"old-key": TOKEN})
    with _failing_replace(monkeypatch, "admin-keys.json"):
        with pytest.raises(OSError):
            keystore.set_admin(tws, {"new-key": TOKEN2})
    assert keystore.get_value(tws, "old-key") == TOKEN
    assert keystore.admin_names(tws) == ["old-key"]
    assert not list(hp.key_dir(tws).rglob("*.tmp"))


def test_a_damaged_key_file_refuses_and_does_not_leak(tws):
    keystore.add(tws, "k", "token", TOKEN)
    d = hp.key_dir(tws)
    hp._write_private(d / "keys.json", '{"schema": "orch.keys/1", "keys": {"k": {"value": "' + TOKEN + '"')
    for call in (lambda: keystore.get_value(tws, "k"), lambda: keystore.list_keys(tws)):
        with pytest.raises(Refused, match="damaged") as e:
            call()
        assert TOKEN not in str(e.value) and TOKEN not in repr(e.value.__cause__)
    hp._write_private(d / "keys.json", json.dumps({"schema": "orch.keys/1", "keys": {"k": {"type": "x"}}}))
    with pytest.raises(Refused, match="damaged"):  # a wrong shape never writes over it silently
        keystore.add(tws, "other", "token", TOKEN2)


# ------------------------------------------------------------------------------ binding (N17)


def test_the_local_id_is_bound_to_the_workspace_path(tws, acct):
    keystore.add(tws, "k", "token", TOKEN)
    b = json.loads((hp.key_dir(tws) / "binding.json").read_text())
    assert b["realpath"] == os.path.realpath(tws)
    # a copy has the same .local-id and another path: refused, and it can neither read nor write keys
    copy = acct / ".orch-test" / "copy"
    shutil.copytree(tws, copy)
    for call in (
        lambda: keystore.get_value(copy, "k"),
        lambda: keystore.list_keys(copy),
        lambda: keystore.add(copy, "x", "token", TOKEN2),
        lambda: keystore.set_admin(copy, {"a": TOKEN2}),
        lambda: hp.human_key(copy),
    ):
        with pytest.raises(Refused, match="copied or moved"):
            call()
    assert keystore.get_value(tws, "k") == TOKEN  # the original is unaffected


def test_a_forged_id_file_cannot_reach_another_workspaces_keys(tws, acct):
    keystore.add(tws, "k", "token", TOKEN)
    other = acct / ".orch-test" / "other"
    (other / ".orch").mkdir(parents=True)
    (other / ".orch" / ".local-id").write_text((tws / ".orch" / ".local-id").read_text())  # agent-writable
    with pytest.raises(Refused, match="copied or moved"):
        keystore.get_value(other, "k")
    with pytest.raises(Refused, match="copied or moved"):
        keystore.add(other, "k2", "token", TOKEN2)


def test_a_moved_workspace_is_refused_and_a_link_to_the_same_folder_is_not(tws, acct):
    keystore.add(tws, "k", "token", TOKEN)
    link = acct / ".orch-test" / "link"
    link.symlink_to(tws)
    assert keystore.get_value(link, "k") == TOKEN  # same folder through a link
    moved = acct / ".orch-test" / "moved"
    tws.rename(moved)
    with pytest.raises(Refused, match="copied or moved"):
        keystore.get_value(moved, "k")


def test_a_missing_or_damaged_binding_refuses_instead_of_rebinding(tws):
    keystore.add(tws, "k", "token", TOKEN)
    b = hp.key_dir(tws) / "binding.json"
    hp._write_private(b, "{broken")
    with pytest.raises(Refused, match="unreadable"):
        keystore.get_value(tws, "k")
    b.unlink()
    with pytest.raises(Refused, match="copied or moved"):  # a read never creates a binding
        keystore.get_value(tws, "k")


# ------------------------------------------------------------------------------ home pairing (N11/N14)


def test_a_real_workspace_with_another_orch_home_is_refused(acct, monkeypatch, tmp_path):
    ws = acct / "projects" / "real"  # not under .orch-test: a real workspace
    (ws / ".orch").mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("ORCH_HOME", str(other))
    with pytest.raises(hp.HomeRefused):
        keystore.add(ws, "k", "token", TOKEN)
    with pytest.raises(hp.HomeRefused):
        keystore.set_admin(ws, {"a": TOKEN})
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))  # a test home is no fallback either
    with pytest.raises(hp.HomeRefused):
        keystore.add(ws, "k", "token", TOKEN)
    assert not any(other.iterdir()) and not (acct / ".orch-tool").exists()
    assert not (acct / ".orch-test" / "home").exists()
    assert not (ws / ".orch" / "keys").exists()


def test_a_real_workspace_uses_the_default_home_in_the_account_not_a_real_one(acct, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")  # a test install never pairs a real workspace
    ws = acct / "projects" / "real"
    (ws / ".orch").mkdir(parents=True)
    monkeypatch.delenv("ORCH_HOME", raising=False)
    keystore.add(ws, "k", "token", TOKEN)
    assert (acct / ".orch-tool" / "keys").is_dir()  # the fake account's default home
    assert keystore.get_value(ws, "k") == TOKEN
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-tool"))  # naming the default itself is fine
    assert keystore.get_value(ws, "k") == TOKEN


def test_a_test_workspace_with_the_default_home_is_refused(tws, acct, monkeypatch):
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-tool"))
    with pytest.raises(hp.HomeRefused):
        keystore.add(tws, "k", "token", TOKEN)
    assert not (acct / ".orch-tool").exists()


def test_tests_never_wrote_into_the_real_account_home(tws):
    keystore.add(tws, "k", "token", TOKEN)
    real = Path(os.path.expanduser("~"))
    assert not str(hp.key_dir(tws)).startswith(str(real / ".orch-tool"))


# ------------------------------------------------------------------------------ no value in messages


def test_no_key_value_in_any_error_log_or_output(tws, capsys, caplog):
    keystore.add(tws, "k", "token", TOKEN)
    keystore.add(tws, "kf", "key-file", TOKEN2.encode())
    errors = []
    for call in (
        lambda: keystore.add(tws, "k", "token", "x" + TOKEN + "\n"),
        lambda: keystore.add(tws, TOKEN + "/x", "token", TOKEN2),  # a value used as a name
        lambda: keystore.add(tws, "j", "json", TOKEN),
        lambda: keystore.get_value(tws, TOKEN + "/x"),
        lambda: keystore.remove(tws, TOKEN + "/x"),
        lambda: seed_profiles(tws, {"p": {"env": {"A": "k"}, "set": {"B": TOKEN}}}),
        lambda: seed_profiles(tws, {"p": {"env": {TOKEN: "k"}}}),
        lambda: seed_profiles(tws, {"p": {"env": {"A": TOKEN2 + "/x"}}}),
        lambda: keystore.record_write(tws, TOKEN, {}),
    ):
        with pytest.raises(Refused) as e:
            call()
        errors.append(str(e.value))
    skipped = keystore.set_admin(tws, {"short": "abc", TOKEN + "/bad": TOKEN2})
    out, err = capsys.readouterr()
    blob = "\n".join(errors + skipped + [out, err, caplog.text])
    assert TOKEN not in blob and TOKEN2 not in blob


# ------------------------------------------------------------------------------ the relay refresh


def _snap_keys(rel, **creds):
    rel.snapshot.update(version=rel.snapshot.get("version", 1) + 1, skills=[], mcp={}, credentials=creds)


def test_relay_refresh_writes_the_keys_into_the_guarded_home_not_the_workspace(rel, run, tws, monkeypatch):
    monkeypatch.chdir(tws)
    turn_on(tws, "relay")
    legacy = tws / ".orch" / "secrets" / "credentials.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"OLD_ONE": "old-value-0123456789"}))  # left by an older refresh
    code, out, err = run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)
    assert code == 0, (out, err)
    _snap_keys(
        rel, DB_URL="pg://db.example/prod", SVC={"type": "service_account", "k": "abcdefghij"}, tiny="abc"
    )
    code, out, err = run("relay", "refresh")
    assert code == 0, (out, err)
    assert keystore.get_value(tws, "DB_URL") == "pg://db.example/prod"
    assert json.loads(keystore.get_value(tws, "SVC")) == {"type": "service_account", "k": "abcdefghij"}
    assert keystore.admin_names(tws) == ["DB_URL", "SVC"]
    assert "tiny" in out and "too short" in out and "abc" not in out.replace("tiny", "")
    gh = hp.guarded_home(tws)
    assert (gh / "keys").is_dir() and str(hp.key_dir(tws)).startswith(str(gh))
    # the workspace holds no key after a refresh: no credentials.json, and no value anywhere under .orch/
    assert not legacy.exists()
    text = _tree_text(tws / ".orch")
    for v in ("pg://db.example/prod", "abcdefghij", "old-value-0123456789"):
        assert v not in text
    assert not (tws / ".orch" / "tmp-refresh").exists()
    # the next refresh replaces the set whole
    _snap_keys(rel, OTHER="other-value-9876543")
    assert run("relay", "refresh")[0] == 0
    assert keystore.admin_names(tws) == ["OTHER"]
    with pytest.raises(Refused, match="no such key"):
        keystore.get_value(tws, "DB_URL")


def test_admin_keys_are_refused_when_the_home_does_not_pair_and_empty_is_a_no_op(acct, monkeypatch, tmp_path):
    from orch import relay

    ws = acct / "projects" / "real"  # real workspace, ORCH_HOME elsewhere
    (ws / ".orch" / "secrets").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("ORCH_HOME", str(elsewhere))
    skipped: list[str] = []
    relay._admin_keys(ws, {}, skipped)  # nothing to store, nothing refused
    with pytest.raises(hp.HomeRefused) as e:
        relay._admin_keys(ws, {"DB_URL": "pg://db.example/prod"}, skipped)
    assert "pg://db.example/prod" not in str(e.value)
    assert not any(elsewhere.iterdir()) and not (acct / ".orch-tool").exists()
    assert not (ws / ".orch" / "secrets" / "credentials.json").exists()


def test_a_refresh_with_keys_and_an_unpaired_home_changes_nothing(acct, monkeypatch, tmp_path):
    import base64

    from orch import relay

    ws = acct / "projects" / "real"  # real workspace, ORCH_HOME elsewhere
    (ws / ".orch").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("ORCH_HOME", str(elsewhere))
    snap = {
        "version": 3,
        "skills": [
            {
                "name": "acme-sql",
                "files": {"SKILL.md": base64.b64encode(b"---\nname: acme-sql\n---\n").decode()},
            }
        ],
        "mcp": {"sql": {"command": "x"}},
        "credentials": {"DB_URL": "pg://db.example/prod"},
        "workspaces": {"workspaces": [{"id": "ws_x", "name": "X"}], "phones": []},
    }
    monkeypatch.setattr(relay, "_api", lambda *a, **k: (200, snap))
    with pytest.raises(hp.HomeRefused):
        relay.refresh(ws)
    assert not (ws / ".agents").exists()  # no skill, no workspaces.json
    sec = ws / ".orch" / "secrets"
    assert not (sec / "mcp.json").exists() and not (sec / "shared.json").exists()
    assert not (sec / "credentials.json").exists() and not any(elsewhere.iterdir())
    assert not (ws / ".orch" / "tmp-refresh").exists()


def _refresh_fixture(tws, monkeypatch):
    import base64

    from orch import relay

    snap = {
        "version": 3,
        "skills": [
            {
                "name": "acme-sql",
                "files": {"SKILL.md": base64.b64encode(b"---\nname: acme-sql\n---\n").decode()},
            }
        ],
        "mcp": {"sql": {"command": "x"}},
        "credentials": {"DB_URL": "pg://db.example/prod"},
        "workspaces": {"workspaces": [{"id": "ws_x", "name": "X"}], "phones": []},
    }
    monkeypatch.setattr(relay, "_api", lambda *a, **k: (200, snap))
    return relay


def _nothing_replaced(ws):
    sec = ws / ".orch" / "secrets"
    assert not (ws / ".agents" / "skills" / "acme-sql").exists()
    assert not (ws / ".agents" / "skills" / "orch-relay" / "workspaces.json").exists()
    assert not (sec / "mcp.json").exists() and not (sec / "shared.json").exists()


def test_a_planted_credentials_link_stops_the_whole_refresh(tws, monkeypatch, tmp_path):
    relay = _refresh_fixture(tws, monkeypatch)
    sec = tws / ".orch" / "secrets"
    sec.mkdir(parents=True)
    target = tmp_path / "somewhere-else"
    target.write_text("keep me")
    (sec / "credentials.json").symlink_to(target)
    with pytest.raises(Refused):
        relay.refresh(tws)
    _nothing_replaced(tws)
    assert target.read_text() == "keep me"


def test_a_damaged_key_file_stops_the_whole_refresh(tws, monkeypatch):
    relay = _refresh_fixture(tws, monkeypatch)
    keystore.add(tws, "mine", "token", TOKEN)
    for name in ("keys.json", "admin-keys.json"):
        path = hp.key_dir(tws) / name
        before = path.read_bytes() if path.exists() else None
        hp._write_private(path, "{broken")
        with pytest.raises(Refused, match="damaged"):
            relay.refresh(tws)
        _nothing_replaced(tws)
        if before is None:
            path.unlink()
        else:
            hp._write_private(path, before.decode())


def test_an_existing_key_folder_without_a_binding_is_refused_and_not_written(tws):
    from orch import addons

    ws_id = addons.workspace_id(tws, create=True)
    home = hp.guarded_home(tws)
    d = home / "keys" / ws_id  # pre-created, e.g. by something that knows the id
    hp._private_dir(d, home)
    (d / "human.key").write_text("x")
    before = sorted(p.name for p in d.iterdir())
    for call in (
        lambda: keystore.add(tws, "k", "token", TOKEN),
        lambda: keystore.set_admin(tws, {"a": TOKEN}),
        lambda: keystore.record_write(tws, "dev", {}),
        lambda: keystore.get_value(tws, "k"),
        lambda: hp.human_key(tws),
    ):
        with pytest.raises(Refused, match="copied or moved"):
            call()
    assert sorted(p.name for p in d.iterdir()) == before  # no binding, no lock, nothing written


def test_an_empty_new_key_folder_is_bound_once_and_the_first_binding_wins(tws, acct):
    keystore.add(tws, "k", "token", TOKEN)
    d = hp.key_dir(tws)
    first = (d / "binding.json").read_text()
    other = acct / ".orch-test" / "other"
    other.mkdir()
    hp._bind_new(other, d)  # a later binding attempt never overwrites
    assert (d / "binding.json").read_text() == first
    assert not list(d.glob(".binding.*"))


# ------------------------------------------------------------------------------ loose key files (set aside)

SENTINEL = "sentinel-VALUE-never-used-0042"


def _loose_setup(tws):
    keystore.add(tws, "k1", "token", SENTINEL)
    keystore.add(tws, "k2", "password", TOKEN2)
    return hp.key_dir(tws)


@posix_only
@pytest.mark.parametrize("mode", [0o644, 0o660, 0o604, 0o666])
def test_a_loose_keys_file_is_set_aside_and_its_values_are_never_used(tws, mode, caplog):
    d = _loose_setup(tws)
    os.chmod(d / "keys.json", mode)
    with pytest.raises(Refused, match="must be entered again") as e:
        keystore.get_value(tws, "k1")
    assert SENTINEL not in str(e.value)
    assert not (d / "keys.json").exists()  # renamed, not chmod'ed and trusted
    aside = list(d.glob("keys.json.loose-*"))
    assert len(aside) == 1 and _mode(aside[0]) == 0o600
    assert "keys.json" in caplog.text and SENTINEL not in caplog.text and TOKEN2 not in caplog.text
    items = keystore.list_keys(tws)
    assert [(i["name"], i["state"], i["type"]) for i in items] == [
        ("k1", "needs-reentry", None),
        ("k2", "needs-reentry", None),
    ]
    assert all(i["note"] == "This key must be entered again." for i in items)
    assert SENTINEL not in json.dumps(items) and TOKEN2 not in json.dumps(items)
    assert not (d / "keys.json").exists()  # reading did not create anything


@posix_only
def test_re_entry_works_and_the_set_aside_file_is_cleaned_up(tws):
    d = _loose_setup(tws)
    os.chmod(d / "keys.json", 0o644)
    keystore.add(tws, "k1", "token", TOKEN)  # a person enters one key again
    assert keystore.get_value(tws, "k1") == TOKEN
    with pytest.raises(Refused, match="must be entered again"):
        keystore.get_value(tws, "k2")
    assert len(list(d.glob("keys.json.loose-*"))) == 1  # k2 still needs it
    assert {i["name"]: i["state"] for i in keystore.list_keys(tws)} == {"k1": "active", "k2": "needs-reentry"}
    keystore.add(tws, "k2", "password", TOKEN2)
    assert not list(d.glob("keys.json.loose-*"))  # nothing left to re-enter: deleted by exact path
    assert [i["state"] for i in keystore.list_keys(tws)] == ["active", "active"]
    assert SENTINEL not in (d / "keys.json").read_text()


@posix_only
def test_removing_a_key_that_needs_re_entry_clears_it(tws):
    d = _loose_setup(tws)
    os.chmod(d / "keys.json", 0o644)
    keystore.remove(tws, "k1")
    assert [i["name"] for i in keystore.list_keys(tws)] == ["k2"]
    (aside,) = d.glob("keys.json.loose-*")
    assert SENTINEL not in aside.read_text()  # rewritten without any value
    keystore.remove(tws, "k2")
    assert not list(d.glob("keys.json.loose-*")) and keystore.list_keys(tws) == []
    with pytest.raises(Refused, match="no such key"):
        keystore.remove(tws, "k2")


@posix_only
def test_a_loose_file_with_bad_names_lists_only_valid_plain_names(tws):
    d = _loose_setup(tws)
    doc = {
        "schema": "orch.keys/1",
        "keys": {"ok-name": {"value": SENTINEL}, "../evil": {}, "a b": {}, "x\nY": {}},
    }
    (d / "keys.json").write_text(json.dumps(doc))
    os.chmod(d / "keys.json", 0o666)
    assert [i["name"] for i in keystore.list_keys(tws)] == ["ok-name"]
    with pytest.raises(Refused, match="must be entered again"):
        keystore.get_value(tws, "ok-name")


@posix_only
def test_another_owner_counts_as_loose(tws, monkeypatch):
    d = _loose_setup(tws)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(d).st_uid + 1)  # the file now looks foreign
    assert keystore._is_loose(d / "keys.json")
    monkeypatch.undo()
    assert not keystore._is_loose(d / "keys.json")


@posix_only
def test_a_loose_admin_file_is_set_aside_and_the_next_refresh_restores_it(tws):
    keystore.set_admin(tws, {"adm1": SENTINEL, "adm2": TOKEN2})
    d = hp.key_dir(tws)
    os.chmod(d / "admin-keys.json", 0o640)
    with pytest.raises(Refused, match="must be entered again"):
        keystore.get_value(tws, "adm1")
    assert [(i["name"], i["source"], i["state"]) for i in keystore.list_keys(tws)] == [
        ("adm1", "admin", "needs-reentry"),
        ("adm2", "admin", "needs-reentry"),
    ]
    assert keystore.admin_names(tws) == []
    keystore.set_admin(tws, {"adm1": TOKEN, "adm3": TOKEN2})  # the refresh is the whole truth
    assert not list(d.glob("admin-keys.json.loose-*"))
    assert keystore.get_value(tws, "adm1") == TOKEN
    assert [i["name"] for i in keystore.list_keys(tws)] == ["adm1", "adm3"]


@posix_only
def test_a_loose_key_file_value_is_set_aside_and_never_read(tws):
    keystore.add(tws, "kf", "key-file", SENTINEL.encode())
    keystore.add(tws, "k", "token", TOKEN)
    d = hp.key_dir(tws)
    os.chmod(d / "files" / "kf", 0o644)
    with pytest.raises(Refused, match="must be entered again") as e:
        keystore.get_value(tws, "kf")
    assert SENTINEL not in str(e.value)
    assert not (d / "files" / "kf").exists() and len(list((d / "files").glob("kf.loose-*"))) == 1
    states = {i["name"]: i["state"] for i in keystore.list_keys(tws)}
    assert states == {"kf": "needs-reentry", "k": "active"}
    assert keystore.get_value(tws, "k") == TOKEN  # the rest still works
    keystore.add(tws, "kf", "key-file", b"fresh bytes")
    assert keystore.get_value(tws, "kf") == b"fresh bytes"
    assert not list((d / "files").glob("kf.loose-*"))
    assert _mode(d / "files" / "kf") == 0o600


@posix_only
def test_a_loose_key_file_is_found_when_listing_and_when_removing(tws):
    keystore.add(tws, "kf", "key-file", SENTINEL.encode())
    d = hp.key_dir(tws)
    os.chmod(d / "files" / "kf", 0o666)
    assert [(i["name"], i["state"]) for i in keystore.list_keys(tws)] == [("kf", "needs-reentry")]
    keystore.remove(tws, "kf")
    assert not list((d / "files").glob("kf*")) and keystore.list_keys(tws) == []


@posix_only
def test_profiles_still_work_while_a_key_needs_re_entry(tws):
    d = _loose_setup(tws)
    os.chmod(d / "keys.json", 0o644)
    seed_profiles(tws, {"p": {"env": {"A": "k1"}, "set": {"B": "plain host"}}})
    assert keystore.read_profiles(tws)["p"]["env"] == {"A": "k1"}
    assert not (d / "keys.json").exists()  # the loose file stayed set aside, never read for values


def test_an_unknown_file_check_refuses_the_call_and_sets_nothing_aside(tws, monkeypatch):
    from orch import winacl

    keystore.add(tws, "k", "token", TOKEN)
    keystore.add(tws, "kf", "key-file", b"filebytes")
    d = hp.key_dir(tws)
    before = sorted(p.name for p in d.rglob("*"))
    with monkeypatch.context() as m:
        m.setattr(hp, "FILE_CHECKS", [lambda p: "unknown"])  # a transient Windows error
        for call in (
            lambda: keystore.get_value(tws, "k"),
            lambda: keystore.list_keys(tws),
            lambda: keystore.add(tws, "k2", "token", TOKEN2),
            lambda: keystore.set_admin(tws, {"a": TOKEN2}),
        ):
            with pytest.raises(Refused):
                call()
    assert sorted(p.name for p in d.rglob("*")) == before  # nothing set aside, nothing written
    assert not list(d.rglob("*.loose-*"))
    assert keystore.get_value(tws, "k") == TOKEN and keystore.get_value(tws, "kf") == b"filebytes"
    assert winacl.Unknown  # the exception type the refusal carries


def test_write_profiles_signs_only_the_names_it_is_told_to(tws):
    keystore.write_profiles(tws, {"p": {"env": {"A": "k"}}}, sign=frozenset({"p"}))
    assert list(keystore.read_verified_profiles(tws)) == ["p"]
    # a profile that is new in the file but not in `sign` stays unsigned
    keystore.write_profiles(tws, {"p": {"env": {"A": "k"}}, "q": {"env": {"A": "k"}}})
    with pytest.raises(Refused, match="changed outside orch"):
        keystore.read_verified_profiles(tws)
    assert hp._ledger_load(tws, hp.PROFILE_LEDGER).get("q") is None
    keystore.write_profiles(tws, {"p": {"env": {"A": "k"}}}, tombstone=frozenset({"q"}))
    # a body edited in the file: refused; rewriting a switch does not re-sign it
    f = hp.key_dir(tws) / "profiles.toml"
    f.write_text(f.read_text().replace('A = "k"', 'B = "k"'))
    prof = keystore.read_profiles(tws)
    prof["p"]["allow_get"] = True
    keystore.write_profiles(tws, prof)
    with pytest.raises(Refused, match="changed outside orch"):
        keystore.read_verified_profiles(tws)
    # a person setting it again signs the new body; removing tombstones
    keystore.write_profiles(tws, {"p": {"env": {"B": "k"}}}, sign=frozenset({"p"}))
    assert list(keystore.read_verified_profiles(tws)) == ["p"]
    keystore.write_profiles(tws, {}, tombstone=frozenset({"p"}))
    assert hp._ledger_load(tws, hp.PROFILE_LEDGER)["p"] is None


def test_an_unreadable_profiles_file_refuses_the_save(tws):
    keystore.write_profiles(tws, {"p": {"env": {"A": "k"}}}, sign=frozenset({"p"}))
    (hp.key_dir(tws) / "profiles.toml").write_text("not [ toml")
    with pytest.raises(Refused):
        keystore.write_profiles(tws, {"p": {"env": {"A": "k"}}}, sign=frozenset({"p"}))


@pytest.mark.parametrize(
    "var",
    [
        "ld_preload",
        "Node_Options",
        "pythonpath",
        "SHELLOPTS",
        "PS4",
        "x_options",
        "GCONV_PATH",
        "GLIBC_TUNABLES",
        "ZDOTDIR",
        "Home",
        "COR_PROFILER_PATH",
        "CORECLR_ENABLE_PROFILING",
        "DOTNET_STARTUP_HOOKS",
        "npm_config_script_shell",
        "RUSTC_WRAPPER",
        "LESSOPEN",
        "EDITOR",
    ],
)
def test_loader_variables_are_refused_in_any_case(tws, var):
    with pytest.raises(Refused):
        seed_profiles(tws, {"p": {"env": {"A": "k"}, "set": {var: "x"}}})
