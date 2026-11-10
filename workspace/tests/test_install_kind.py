"""Install record (written by the installers), install_kind, ORCH_REPO/ORCH_REF gating (N6) and the test-only
launch URL (human-proof.md)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from orch import addons
from orch import humanproof as hp
from orch.errors import Refused

ROOT = Path(__file__).resolve().parents[2]


def _prefix(tmp_path, monkeypatch, record=None, kind=None):
    env = tmp_path / "toolenv"
    env.mkdir(exist_ok=True)
    if kind is not None:
        record = hp.install_record_text(kind, env)
    if record is not None:
        (env / "orch-install.json").write_text(record.replace("@ENV@", os.path.realpath(env)))
    monkeypatch.setattr(hp.sys, "prefix", str(env))
    return env


@pytest.mark.parametrize("kind", ["normal", "dev", "test"])
def test_record_format_roundtrip(tmp_path, monkeypatch, kind):
    env = _prefix(tmp_path, monkeypatch)
    text = hp.install_record_text(kind, env)
    assert json.loads(text) == {"schema": "orch.install/1", "kind": kind, "root": os.path.realpath(env)}
    (env / "orch-install.json").write_text(text)
    assert hp.install_kind() == kind


def test_bad_kinds_are_not_records(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        hp.install_record_text("admin", "/x")
    _prefix(tmp_path, monkeypatch, '{"kind": "admin", "root": "@ENV@"}')
    assert hp.read_install_record() is None


def test_missing_record_on_a_non_source_install_is_normal(tmp_path, monkeypatch):
    _prefix(tmp_path, monkeypatch)
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    assert hp.install_kind() == "normal"
    monkeypatch.setattr(hp, "_source_tree", lambda: True)
    assert hp.install_kind() == "test"  # running from the source tree, as the suite does


def test_installer_records_match_the_format(tmp_path):
    """install.sh's record line, run through sh, equals install_record_text."""
    for kind in ("normal", "test", "dev"):
        out = tmp_path / f"{kind}.json"
        line = [
            ln
            for ln in (ROOT / "install.sh").read_text().splitlines()
            if "orch-install.json" in ln and "printf" in ln
        ]
        assert len(line) == 1
        cmd = line[0].replace('"$TOOL_DIR/orch-install.json"', f"'{out}'")
        subprocess.run(["sh", "-c", f"KIND={kind}; ROOT={tmp_path}; {cmd}"], check=True)
        assert json.loads(out.read_text()) == json.loads(hp.install_record_text(kind, tmp_path))
    sh = (ROOT / "install.sh").read_text()
    assert "ORCH_INSTALL_KIND" in sh and "normal|dev|test" in sh
    ps = (ROOT / "install.ps1").read_text()
    assert "InstallKind" in ps and '"normal","dev","test"' in ps and "orch-install.json" in ps


@pytest.mark.skipif(shutil.which("uv") is None, reason="the installer would fetch uv")
def test_installer_rejects_a_bad_kind():
    r = subprocess.run(
        ["sh", "-c", 'ORCH_INSTALL_KIND=admin sh -c "$(sed -n 1,200p install.sh)" 2>&1 | tail -1'],
        cwd=ROOT, capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": "/nonexistent"},
    )  # fmt: skip
    assert "must be normal, dev or test" in r.stdout


def test_update_carries_the_record_over(tmp_path, monkeypatch):
    env = _prefix(tmp_path, monkeypatch, kind="dev")
    (env / "bin").mkdir()
    monkeypatch.setattr(addons, "run_uv", lambda args: (env / "orch-install.json").unlink())  # the reinstall
    monkeypatch.setattr(addons, "_tool_args", lambda entries: [])
    addons._install_tool([])
    assert hp.read_install_record() == "dev"


# ---------------------------------------------------------------- N6: ORCH_REPO / ORCH_REF


def test_normal_install_ignores_repo_and_ref(tmp_path, monkeypatch, capsys):
    src = tmp_path / "x"
    (src / "workspace").mkdir(parents=True)
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setenv("ORCH_REPO", str(src))
    monkeypatch.setenv("ORCH_REF", "evil")
    assert addons.repo() == addons.DEFAULT_REPO
    assert addons.ref() != "evil"
    assert not addons._is_local(addons.repo())
    assert "official source" in addons.ignored_source_note()


@pytest.mark.parametrize("kind", ["dev", "test"])
def test_dev_and_test_installs_honour_repo_and_ref(tmp_path, monkeypatch, kind):
    src = tmp_path / "x"
    (src / "workspace").mkdir(parents=True)
    monkeypatch.setattr(hp, "install_kind", lambda: kind)
    monkeypatch.setenv("ORCH_REPO", str(src))
    monkeypatch.setenv("ORCH_REF", "develop")
    assert addons.repo() == str(src) and addons.ref() == "develop" and addons._is_local(str(src))
    assert addons.ignored_source_note() is None


def test_normal_install_never_honours_repo_and_ref_not_even_inside_an_update(monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setenv("ORCH_REF", "v2")
    monkeypatch.setenv("ORCH_REPO", "/tmp/x")
    assert addons.ref() != "v2" and addons.repo() == addons.DEFAULT_REPO
    assert not hasattr(addons, "trusted_env_source") and not hasattr(addons, "_ENV_SOURCE_PROVEN")


def test_addon_add_says_so_on_a_normal_install(proj, monkeypatch, capsys):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setenv("ORCH_REPO", "/tmp/x")
    with pytest.raises(Refused):
        addons.add(proj, "no-such-addon", yes=True)
    assert "ORCH_REPO / ORCH_REF are ignored" in capsys.readouterr().err


# ---------------------------------------------------------------- launch URL (test install only)


@pytest.fixture
def tws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    ws = acct / ".orch-test" / "ws"
    (ws / ".orch").mkdir(parents=True)
    (acct / ".orch-test" / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    return ws


def test_launch_url_on_a_test_install(tws):
    url = hp.printable_launch_url(tws, "focus", "http://127.0.0.1:8123")
    token = url.split("#launch=")[1]
    assert url.startswith("http://127.0.0.1:8123/#launch=")
    tok, exp = (hp.key_dir(tws) / "launch-focus.token").read_text().split()  # the ONE format: token, expiry
    assert (
        tok == token and 0 < int(exp) - __import__("time").time() <= hp.LAUNCH_LIFE and hp.LAUNCH_LIFE == 30
    )
    assert oct((hp.key_dir(tws) / "launch-focus.token").stat().st_mode & 0o777) == "0o600"


def test_launch_url_refused_on_dev_normal_and_outside_the_test_folder(tws, tmp_path, monkeypatch):
    for kind in ("dev", "normal"):
        monkeypatch.setattr(hp, "install_kind", lambda k=kind: k)
        with pytest.raises(Refused, match="only on a test install"):
            hp.printable_launch_url(tws, "focus", "http://127.0.0.1:1")
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    other = tmp_path / "acct" / "real-ws"
    other.mkdir()
    with pytest.raises(Refused, match="only on a test install"):
        hp.printable_launch_url(other, "focus", "http://127.0.0.1:1")
    with pytest.raises(Refused):
        hp.write_launch_token(tws, "evil")


def test_start_refuses_print_launch_url_outside_test(proj, monkeypatch, run):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    code, out, err = run("start", "--no-open", "--print-launch-url")
    assert code == 2 and "only on a test install" in (out + err)


# ---------------------------------------------------------------- folder add-ons, tool env guard, json


def _folder_addon(tmp_path):
    f = tmp_path / "mine"
    f.mkdir()
    (f / "pyproject.toml").write_text('[project]\nname = "orch-mine"\nversion = "0.1.0"\n')
    return f


def test_normal_install_refuses_a_folder_addon_without_a_handoff(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    f = _folder_addon(tmp_path)
    with pytest.raises(Refused, match="only you can allow it"):
        addons.add(proj, str(f), yes=True)
    assert addons.registry() == []  # nothing recorded, nothing installed


def test_folder_addon_passes_the_core_check_on_dev_test_and_with_the_handoff(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    assert not addons._local_add_ok()
    with addons.trusted_local_add("a" * 64):
        assert addons._local_add_ok()
    assert not addons._local_add_ok()
    for kind in ("dev", "test"):
        monkeypatch.setattr(hp, "install_kind", lambda k=kind: k)
        assert addons._local_add_ok()
    assert "addon.add_local" in hp.OPS


def test_reinstall_needs_a_record_for_this_environment(tmp_path, monkeypatch):
    env = _prefix(tmp_path, monkeypatch)
    (env / "bin").mkdir()
    (env / "uv-receipt.toml").write_text("")  # a receipt is no trust anchor
    monkeypatch.setattr(addons, "run_uv", addons._REAL_RUN_UV)
    called = []
    monkeypatch.setattr(addons, "_tool_args", lambda e: called.append(1) or [])
    with pytest.raises(Refused, match="tool folder"):  # no record
        addons._install_tool([])
    (env / "orch-install.json").write_text(hp.install_record_text("normal", tmp_path / "other"))
    with pytest.raises(Refused, match="tool folder"):  # a record for another environment
        addons._install_tool([])
    assert not called


def test_reinstall_pins_uv_tool_dir_to_the_recorded_place(tmp_path, monkeypatch):
    env = _prefix(tmp_path, monkeypatch, kind="test")
    (env / "bin").mkdir()
    monkeypatch.setenv("UV_TOOL_DIR", "/agent/chosen")
    monkeypatch.setenv("XDG_DATA_HOME", "/agent/xdg")
    seen = []
    monkeypatch.setattr(addons, "run_uv", lambda a: seen.append(os.environ["UV_TOOL_DIR"]))
    monkeypatch.setattr(addons, "_tool_args", lambda e: [])
    addons._install_tool([])
    assert seen == [os.path.realpath(tmp_path)]  # dirname of the recorded root
    assert os.environ["UV_TOOL_DIR"] == "/agent/chosen"  # restored


def test_env_vars_do_not_steer_the_install_kind(tmp_path, monkeypatch):
    _prefix(tmp_path, monkeypatch, kind="normal")
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    before = hp.install_kind()
    monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "x"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "y"))
    assert hp.install_kind() == before == "normal"


def test_record_for_another_root_is_ignored(tmp_path, monkeypatch):
    _prefix(tmp_path, monkeypatch, hp.install_record_text("test", tmp_path / "elsewhere"))
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    assert hp.read_install_record() is None and hp.install_kind() == "normal"
    _prefix_old = tmp_path / "toolenv" / "orch-install.json"
    _prefix_old.write_text('{"kind": "test"}')  # an old record without root
    assert hp.install_kind() == "normal"


def test_lane_c_layout_tool_env_under_orch_test_testnet(tmp_path, monkeypatch):
    """UV_TOOL_DIR under ~/.orch-test/testnet is legitimate: its record names that environment."""
    env = tmp_path / ".orch-test" / "testnet" / "tools" / "orch-workspace"
    env.mkdir(parents=True)
    (env / "orch-install.json").write_text(hp.install_record_text("test", env))
    monkeypatch.setattr(hp.sys, "prefix", str(env))
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    assert hp.install_kind() == "test"
    monkeypatch.setenv("UV_TOOL_DIR", str(env.parent))
    assert hp.install_kind() == "test"


@pytest.fixture
def rws(tmp_path, monkeypatch):
    """A REAL workspace on a NORMAL install: guarded home = the (temp) account's default orch home."""
    acct = tmp_path / "acct"
    ws = acct / "work" / "ws"
    (ws / ".orch").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.delenv("ORCH_HOME", raising=False)
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    return ws


def test_planted_folder_entry_is_not_installed_on_a_normal_install(rws, tmp_path, capsys):
    from orch import addonsnap

    evil = _folder_addon(tmp_path)
    planted = [
        {"name": "mine", "source": str(evil), "version": "0.1.0"},  # no approval
        {"name": "relay", "source": "built-in", "version": "0.1.0"},
    ]
    args = addons._tool_args(planted)
    assert str(evil) not in args and "--with" in args  # the built-in still goes in
    assert "only you can allow" in capsys.readouterr().err
    snap = addons.prepare_local_add(rws, evil)
    entry = {
        "name": "ok",
        "source": snap["snapshot"],
        "version": "0.1.0",
        "approved": True,
        "hash": snap["hash"],
    }
    assert addons._missing_source(entry) is not None  # right place, but never allowed by a person
    addonsnap.allow(hp.guarded_home(rws), snap["hash"])
    assert snap["snapshot"] in addons._tool_args([entry])  # allowed hash in the right place: installed


def test_snapshot_in_an_agent_chosen_home_is_skipped(tws, tmp_path, monkeypatch, capsys):
    """H1: ORCH_HOME at an agent's folder holding a valid, 'allowed' snapshot must not get installed."""
    from orch import addonsnap

    f = _real_addon(tmp_path)
    snap = addons.prepare_local_add(tws, f)  # under the test home (ORCH_HOME)
    addonsnap.allow(hp.guarded_home(tws), snap["hash"])
    entry = {
        "name": "hello",
        "source": snap["snapshot"],
        "version": "0.1.0",
        "approved": True,
        "hash": snap["hash"],
    }
    assert addons._missing_source(entry) is None  # a test install may use its test home
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")  # the same layout on a normal install
    assert "changed since you allowed it" in addons._missing_source(entry)
    assert snap["snapshot"] not in addons._tool_args([entry])
    # a snapshot folder with a link on the way is no snapshot either
    link = tmp_path / "linkhome"
    link.symlink_to(Path(snap["snapshot"]).parents[3])
    via = link / "keys" / Path(snap["snapshot"]).parents[1].name / "addon-snapshots" / snap["hash"]
    assert addonsnap.home_of(via, snap["hash"]) is None


@pytest.fixture
def throwaway(tmp_path, monkeypatch):
    """A NORMAL install whose account home is faked and whose ORCH_HOME is a trusted throwaway folder (what an
    e2e lane's own HOME looks like). Nothing may ever be written under the account's default orch home."""
    acct = tmp_path / "acct"
    acct.mkdir()
    orch_home = acct / "lane-home"
    orch_home.mkdir()
    ws = acct / "work" / "ws"
    (ws / ".orch").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(orch_home))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.chdir(ws)
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    return acct, orch_home, ws


def test_all_state_lives_in_one_home(throwaway):
    """Why the unit tests missed the registry split: every path was inside a temp tree, and nothing compared
    them. State (registry, running.json, update snapshot) must all come from home()."""
    from orch import services

    acct, orch_home, ws = throwaway
    assert addons.home() == orch_home
    assert addons.registry_path() == orch_home / "addons.json"
    assert services.running_path() == orch_home / "running.json"
    assert not (acct / ".orch-tool").exists()


def test_update_on_a_normal_install_with_another_orch_home_is_refused(throwaway, monkeypatch):
    acct, orch_home, ws = throwaway
    addons._save_registry([{"name": "focus", "source": "built-in", "version": "0.1.0"}])
    ran = []
    monkeypatch.setattr(addons, "run_uv", lambda a: ran.append(a))
    monkeypatch.setattr(addons, "reexec", lambda a: ran.append(a))
    for call in (
        lambda: addons.update(ws),
        lambda: addons._reinstall([], save=True, then=[], root=ws, done="x"),
    ):
        with pytest.raises(hp.HomeRefused, match="different orch folder than your account's") as e:
            call()
        assert "Start orch normally" in str(e.value) and e.value.code == hp.NOT_TOGETHER
    assert ran == [] and not (acct / ".orch-tool").exists()  # nothing installed, real home untouched
    assert addons.registry() and addons.home() == orch_home  # read-only ops still see the list


def test_a_dev_or_test_install_may_update_from_its_own_orch_home(throwaway, monkeypatch):
    acct, orch_home, ws = throwaway
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    addons._save_registry([{"name": "focus", "source": "built-in", "version": "0.1.0"}])
    seen = []
    monkeypatch.setattr(addons, "_install_tool", lambda e: seen.append(e))
    monkeypatch.setattr(addons, "reexec", lambda a: None)
    addons.update(ws)
    assert [e["name"] for e in seen[0]] == ["focus"]
    assert not (acct / ".orch-tool").exists()


def test_a_crafted_registry_is_filtered(throwaway, capsys):
    acct, orch_home, ws = throwaway
    (orch_home / "addons.json").write_text(
        json.dumps(
            [
                {
                    "name": "focus",
                    "source": "built-in",
                    "version": "0.1.0",
                    "spec": "git+https://evil/x",
                    "extra": 1,
                },
                {
                    "name": "evil",
                    "source": "built-in",
                    "version": "1",
                },  # a fake built-in: orch does not ship it
                {"name": "../x", "source": "built-in", "version": "1"},  # bad name
                {"name": "Bad Name", "source": "/agent/dir", "version": "1"},
                {"name": "relay", "source": "built-in", "version": "1"},  # reserved/core: not a tool entry
            ]
        )
    )
    reg = addons.registry()
    assert reg == [{"name": "focus", "source": "built-in", "version": "0.1.0"}]  # extra fields stripped
    err = capsys.readouterr().err
    assert "'evil' was ignored" in err and "not a valid add-on name" in err


def test_a_planted_hashless_folder_entry_rides_no_approval(rws, tmp_path, capsys):
    from orch import addonsnap

    good = _folder_addon(tmp_path)
    snap = addons.prepare_local_add(rws, good)
    addonsnap.allow(hp.guarded_home(rws), snap["hash"])
    planted = {"name": "planted", "source": "/agent/dir", "version": "0.1.0"}
    mine = {
        "name": "mine",
        "source": snap["snapshot"],
        "version": "0.1.0",
        "approved": True,
        "hash": snap["hash"],
    }
    with addons.trusted_local_add(snap["hash"]):
        args = addons._tool_args([planted, mine])
    assert "/agent/dir" not in args and snap["snapshot"] in args
    assert "only you can allow" in capsys.readouterr().err


def test_install_uses_the_snapshot_not_the_live_folder(tws, tmp_path, monkeypatch):
    f = _real_addon(tmp_path)
    snap = addons.prepare_local_add(tws, f)
    assert addons.local_add_target(tws, f) == snap["hash"] and snap["short"] == snap["hash"][:8]
    (f / "evil.py").write_text("print('swapped in after the click')")  # the live folder changes
    got = _capture_reinstall(monkeypatch)
    with addons.trusted_local_add(snap["hash"]), pytest.raises(Refused, match="changed since you allowed"):
        addons.add(tws, str(f), yes=True)
    (f / "evil.py").unlink()  # content back as allowed: installs, from the snapshot
    with addons.trusted_local_add(snap["hash"]):
        addons.add(tws, str(f), yes=True)
    entry = got["entries"][-1]
    assert entry["source"] == snap["snapshot"] and entry["hash"] == snap["hash"] and entry["approved"] is True
    assert entry["folder"] == str(f.resolve())
    assert not (Path(snap["snapshot"]) / "evil.py").exists()
    from orch import addonsnap

    assert snap["hash"] in addonsnap._allowed(hp.guarded_home(tws))  # recorded inside the hand-off


def test_tampered_snapshot_is_refused_on_reinstall(tws, tmp_path, capsys):
    from orch import addonsnap

    f = _real_addon(tmp_path)
    snap = addons.prepare_local_add(tws, f)
    addonsnap.allow(hp.guarded_home(tws), snap["hash"])
    entry = {
        "name": "hello",
        "source": snap["snapshot"],
        "version": "0.1.0",
        "approved": True,
        "hash": snap["hash"],
    }
    assert addons._missing_source(entry) is None
    (Path(snap["snapshot"]) / "evil.py").write_text("x = 1")  # tampered
    assert "changed since you allowed it" in addons._missing_source(entry)
    args = addons._tool_args([entry])
    assert snap["snapshot"] not in args and "left out" in capsys.readouterr().err
    entry2 = {**entry, "hash": "0" * 64, "source": str(f)}
    assert "changed since you allowed it" in addons._missing_source(entry2)


# ------------------------------------ M3 / M1: updates of installs that predate the record


def _old_install(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "tool_env_change_ok", lambda: None)  # the home rule has its own tests
    env = _prefix(tmp_path, monkeypatch)  # no record
    (env / "bin").mkdir()
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    monkeypatch.setattr(addons, "_tool_args", lambda e: [])
    return env


def test_update_of_an_install_without_a_record_writes_a_normal_one(tmp_path, monkeypatch):
    env = _old_install(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(addons, "run_uv", lambda a: seen.append(os.environ.get("UV_TOOL_DIR")))
    addons._install_tool([])
    assert seen == [os.path.realpath(tmp_path)]
    assert hp.read_install_record() == "normal"
    assert json.loads((env / "orch-install.json").read_text())["root"] == os.path.realpath(env)


def test_an_update_never_changes_the_kind(tmp_path, monkeypatch):
    for kind in ("test", "dev", "normal"):
        env = _prefix(tmp_path, monkeypatch)
        (env / "bin").mkdir(exist_ok=True)
        monkeypatch.setattr(hp, "_source_tree", lambda: False)
        monkeypatch.setattr(addons, "_tool_args", lambda e: [])
        (env / "orch-install.json").write_text(hp.install_record_text(kind, env))
        monkeypatch.setattr(addons, "run_uv", lambda a, e=env: (e / "orch-install.json").unlink())
        addons._install_tool([])
        assert hp.read_install_record() == kind
        (env / "orch-install.json").unlink()
    (env / "orch-install.json").write_text(
        hp.install_record_text("test", tmp_path / "other")
    )  # not for this env
    monkeypatch.setattr(addons, "run_uv", lambda a: None)
    addons._install_tool([])
    assert hp.read_install_record() == "normal"  # a foreign record is never elevated to


def test_windows_update_keeps_the_record_and_pins_the_tool_dir(tmp_path, monkeypatch):
    from orch import winfinish

    env = _old_install(tmp_path, monkeypatch)
    for rec in (None, "test"):
        if rec:
            (env / "orch-install.json").write_text(hp.install_record_text(rec, env))
        got: dict = {}
        monkeypatch.setattr(winfinish, "needed", lambda: True)
        monkeypatch.setattr(winfinish, "pending", lambda h: False)
        monkeypatch.setattr(addons, "_which_uv", lambda: "uv")
        monkeypatch.setattr(
            winfinish,
            "start",
            lambda *a, _g=got, **k: _g.update(extra=a[6] if len(a) > 6 else k.get("extra")) or "log",
        )
        assert addons._reinstall([], save=False, then=[], root=tmp_path, done="x") is False
        assert got["extra"]["env"] == {"UV_TOOL_DIR": os.path.realpath(tmp_path)}
        path, text = got["extra"]["record"]
        assert path == str(env / "orch-install.json")
        assert json.loads(text)["kind"] == (rec or "normal") and json.loads(text)["root"] == os.path.realpath(
            env
        )


def test_finisher_applies_env_and_record(tmp_path):
    import subprocess
    import sys

    from orch import winfinish

    (tmp_path / "finish.py").write_text(winfinish.FINISHER, encoding="utf-8")
    rec = tmp_path / "orch-install.json"
    code = f"import os,sys; open(r'{tmp_path}/seen','w').write(os.environ['UV_TOOL_DIR'])"
    job = {
        "uv": [sys.executable, "-c", code],
        "free": [],
        "wait": 5,
        "uv_timeout": 30,
        "registry": None,
        "env": {"UV_TOOL_DIR": "/pinned"},
        "record": [str(rec), '{"kind": "normal"}\n'],
        "then": [],
        "log": str(tmp_path / "finish.log"),
        "done": "ok",
        "pending": str(tmp_path / "finish.pending"),
    }
    (tmp_path / "finish.pending").write_text("1")
    (tmp_path / "job.json").write_text(json.dumps(job))
    r = subprocess.run([sys.executable, "-I", str(tmp_path / "finish.py"), str(tmp_path / "job.json")])
    assert r.returncode == 0 and (tmp_path / "seen").read_text() == "/pinned"
    assert json.loads(rec.read_text()) == {"kind": "normal"}


def test_start_json_with_launch_urls_is_valid_json(proj, monkeypatch, capsys):
    from orch import cli, services

    monkeypatch.setattr(hp, "is_test_workspace", lambda r: True)
    monkeypatch.setattr(services, "start", lambda root: [{"addon": "focus", "url": "http://127.0.0.1:9"}])
    monkeypatch.setattr(hp, "printable_launch_url", lambda r, s, b: b + "/#launch=tok")
    assert cli.main(["start", "--json", "--print-launch-url"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["launch"] == [{"addon": "focus", "url": "http://127.0.0.1:9/#launch=tok"}]


def test_installers_print_a_visible_line_and_validate_the_kind():
    sh = (ROOT / "install.sh").read_text()
    ps = (ROOT / "install.ps1").read_text()
    assert "INSTALL: this orch is marked" in sh and "INSTALL: this orch is marked" in ps
    assert "ConvertTo-Json" in ps and "-notin" in ps and "ORCH_INSTALL_KIND" in ps


# ---------------------------------------------------------------- snapshots (content-bound approval)


def _real_addon(tmp_path, name="hello"):
    from test_addons import make_addon

    return make_addon(tmp_path, name)


def _capture_reinstall(monkeypatch):
    got = {}

    def fake(entries, **kw):
        got["entries"] = entries
        return True

    monkeypatch.setattr(addons, "_reinstall", fake)
    return got


def test_snapshot_refuses_links_and_big_files(tws, tmp_path):
    f = _real_addon(tmp_path)
    (f / "link").symlink_to("/etc/passwd")
    with pytest.raises(Refused, match="link or a special file"):
        addons.prepare_local_add(tws, f)
    (f / "link").unlink()
    (f / "big.bin").write_bytes(b"0" * (5 * 1024 * 1024 + 1))
    with pytest.raises(Refused, match="cannot be read safely"):
        addons.prepare_local_add(tws, f)


def test_same_content_same_hash_and_build_output_ignored(tws, tmp_path):
    f = _real_addon(tmp_path)
    a = addons.prepare_local_add(tws, f)["hash"]
    (f / "build").mkdir()
    (f / "build" / "x").write_text("generated")
    assert addons.prepare_local_add(tws, f)["hash"] == a
    (f / "pyproject.toml").write_text("changed = 1")
    assert addons.prepare_local_add(tws, f)["hash"] != a


# ---------------- simulated Windows (profile folder, case, reparse)


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(hp, "_is_windows", lambda: True)
    monkeypatch.setattr(os.path, "realpath", lambda p: str(p))  # the simulated paths are already real


PROFILE = "C:\\Users\\Pat"


def test_windows_prefix_is_case_insensitive_and_component_wise(win):
    ok = hp.home_ok
    ws = PROFILE + "\\.orch-test\\e2e\\ws"
    home = PROFILE + "\\.orch-test\\e2e\\.orch-tool"
    assert ok(PROFILE, "test", True, ws, home)
    assert ok(PROFILE, "dev", True, ws.upper(), home.lower())  # NTFS ignores case
    assert ok(PROFILE.lower(), "test", True, ws, home)
    assert not ok(PROFILE, "test", True, PROFILE + "\\.orch-testX\\ws", PROFILE + "\\.orch-testX\\h")
    assert not ok(PROFILE, "normal", True, ws, home)  # no test path on a normal install
    assert not ok(PROFILE, "test", False, ws, home)  # prefix is a link / reparse point
    assert ok(PROFILE, "normal", True, "D:\\work\\acme", PROFILE + "\\.ORCH-TOOL")  # default home
    assert not ok(PROFILE, "test", True, "D:\\work\\acme", PROFILE + "\\.orch-test\\evil\\h")


def test_windows_forward_slashes_compare_like_backslashes(win):
    assert hp._under("C:/Users/Pat/.orch-test/x", PROFILE + "\\.orch-test")
    assert not hp._under("C:\\Users\\Pat\\.orch-test", PROFILE + "\\.orch-test")  # the prefix itself


class _St:
    def __init__(self, attrs=0, mode=0o40700):
        self.st_mode, self.st_file_attributes = mode, attrs


def test_windows_reparse_point_is_no_test_prefix(win, monkeypatch):
    monkeypatch.setattr(hp, "_lstat", lambda p: _St(0))
    assert hp._prefix_is_real_dir(Path(PROFILE))
    monkeypatch.setattr(hp, "_lstat", lambda p: _St(hp.REPARSE))  # a junction or symlink
    assert not hp._prefix_is_real_dir(Path(PROFILE))
    monkeypatch.setattr(hp, "_lstat", lambda p: _St(0, 0o100600))  # a file
    assert not hp._prefix_is_real_dir(Path(PROFILE))


def test_windows_is_test_workspace(win, monkeypatch):
    monkeypatch.setattr(hp, "account_home", lambda: Path(PROFILE))
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    monkeypatch.setattr(hp, "_lstat", lambda p: _St(0))
    assert hp.is_test_workspace(Path(PROFILE + "\\.ORCH-TEST\\testnet\\ws"))
    assert not hp.is_test_workspace(Path(PROFILE + "\\Documents\\ws"))
    monkeypatch.setattr(hp, "_lstat", lambda p: _St(hp.REPARSE))
    assert not hp.is_test_workspace(Path(PROFILE + "\\.orch-test\\testnet\\ws"))
    monkeypatch.setattr(hp, "_lstat", lambda p: _St(0))
    monkeypatch.setattr(hp, "install_kind", lambda: "dev")
    assert not hp.is_test_workspace(Path(PROFILE + "\\.orch-test\\testnet\\ws"))  # test installs only


# ---------------------------------------------------------------- plain refusal first (before any hand-off)


@pytest.mark.parametrize(
    "argv",
    [
        ["update"],
        ["addon", "add", "focus", "--yes"],
        ["addon", "add", "./mine", "--yes"],
        ["addon", "uninstall", "focus"],
    ],
)
def test_other_orch_home_gets_the_plain_text_first(throwaway, monkeypatch, capsys, argv):
    from orch import cli

    acct, orch_home, ws = throwaway
    (ws / "mine").mkdir(exist_ok=True)
    (ws / "mine" / "pyproject.toml").write_text('[project]\nname = "orch-mine"\nversion = "0.1.0"\n')
    ran = []
    monkeypatch.setattr(addons, "run_uv", lambda a: ran.append(a))
    monkeypatch.setattr(addons, "reexec", lambda a: ran.append(a))
    queued = []
    monkeypatch.setattr(hp, "request_handoff", lambda *a, **k: queued.append(a) or True)
    code = cli.main(argv)
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert code == 2 and hp.MSG_ENV_CHANGE in text
    assert "Do this in the dashboard" not in text and "dashboard on this computer" not in text
    assert queued == [] and ran == []  # nothing queued as a hand-off, nothing installed
    assert not (acct / ".orch-tool").exists()  # real home untouched
    assert not (orch_home / "keys").exists()  # and no snapshot / key written for the folder either


def test_the_check_does_not_block_list_or_turning_on_in_the_workspace(throwaway, capsys):
    from orch import cli

    assert cli.main(["addon", "list"]) == 0
    assert cli.main(["update", "--project-only"]) in (0, 2)
    assert hp.MSG_ENV_CHANGE not in capsys.readouterr().err
