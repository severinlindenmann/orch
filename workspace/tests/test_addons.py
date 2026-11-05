import io
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from orch import addons, cli
from orch.errors import Refused

MANIFEST = """\
schema = "orch.addon/1"
orch_api = 1
name = "{name}"
version = "0.1.0"
description = "Says hello."
run = "{module}"
skill = "skills/orch-{name}"
ticket_ext = "ext.schema.json"
background = {bg}
{extra}
[dashboard]
label = "Hello"
icon = "star"
order = 20

[[ticket_view]]
field = "greeting"
label = "Greeting"
format = "text"
"""

MAIN = """\
import json, os, sys
from pathlib import Path
if sys.argv[1:2] == ["stop"]:
    Path(os.environ["ORCH_ROOT"], "stopped.txt").write_text("stopped", encoding="utf-8")
    sys.exit(0)
if sys.argv[1:2] == ["fail"]:
    sys.exit(3)
print(json.dumps({"argv": sys.argv[1:], "addon": os.environ.get("ORCH_ADDON"),
                  "root": os.environ.get("ORCH_ROOT"), "bin": bool(os.environ.get("ORCH_BIN")),
                  "cwd": os.getcwd()}))
"""


def make_addon(base: Path, name="hello", bg=False, extra="", mutate=None) -> Path:
    module = "orch_" + name.replace("-", "_")
    folder = base / name
    pkg = folder / "src" / module
    (pkg / "skills" / f"orch-{name}").mkdir(parents=True)
    (folder / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (pkg / "__init__.py").write_text(f"open(r'{base}/IMPORTED-{name}', 'w').write('x')\n", encoding="utf-8")
    (pkg / "__main__.py").write_text(MAIN, encoding="utf-8")
    text = MANIFEST.format(name=name, module=module, bg=str(bg).lower(), extra=extra)
    if mutate:
        text = mutate(text)
    (pkg / "orch-addon.toml").write_text(text, encoding="utf-8")
    sk = pkg / "skills" / f"orch-{name}"
    (sk / "SKILL.md").write_text(f"---\nname: orch-{name}\ndescription: d\n---\nbody\n", encoding="utf-8")
    (sk / "AGENTS-block.md").write_text(f"## orch-{name}\nRead the skill.\n", encoding="utf-8")
    schema = {
        "type": "object",
        "properties": {"greeting": {"type": "string", "maxLength": 5}},
        "additionalProperties": False,
    }
    (pkg / "ext.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return folder


@pytest.fixture
def run(capfd):
    """Like conftest's run, but captures at file-descriptor level so add-on subprocess output is seen too."""

    def _run(*argv):
        code = cli.main(list(argv))
        cap = capfd.readouterr()
        return code, cap.out, cap.err

    return _run


@pytest.fixture
def uv_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(addons, "run_uv", lambda args: calls.append(args))

    def reexec(args):
        if cli.main(args) != 0:
            raise Refused("project step failed")

    monkeypatch.setattr(addons, "reexec", reexec)
    return calls


@pytest.fixture
def hello(tmp_path, monkeypatch, uv_calls):
    """A local add-on folder; 'installing' it makes its package importable and registers its entry point."""
    folder = make_addon(tmp_path / "src-addons")
    eps = {}
    monkeypatch.setattr(addons, "_entry_points", lambda: dict(eps))
    orig = addons.run_uv

    def fake_uv(args):
        orig(args)
        sys.path.insert(0, str(folder / "src"))
        monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
        eps["hello"] = "orch_hello"

    monkeypatch.setattr(addons, "run_uv", fake_uv)
    yield folder
    if str(folder / "src") in sys.path:
        sys.path.remove(str(folder / "src"))


def install(run, folder):
    code, out, err = run("addon", "add", str(folder), "--yes")
    assert code == 0, err


# ---- discovery and manifest -------------------------------------------------------------------------


def test_discovery_never_imports_addon_code(tmp_path, monkeypatch):
    folder = make_addon(tmp_path / "a")
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    addons._save_registry([{"name": "hello", "source": str(folder), "version": "0.1.0"}])
    found = addons.discover()
    assert list(found) == ["hello"] and found["hello"]["version"] == "0.1.0"
    assert not (tmp_path / "a" / "IMPORTED-hello").exists()
    assert "orch_hello" not in sys.modules


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace('name = "hello"', 'name = "ticket"'),  # reserved core name
        lambda t: t.replace('name = "hello"', 'name = "Hello"'),
        lambda t: t.replace('skill = "skills/orch-hello"', 'skill = "../outside"'),
        lambda t: t.replace('skill = "skills/orch-hello"', 'skill = "/etc"'),
        lambda t: t.replace('ticket_ext = "ext.schema.json"', 'ticket_ext = "../../x.json"'),
        lambda t: t.replace('icon = "star"', 'icon = "rocket"'),
        lambda t: t.replace("orch_api = 1", "orch_api = 2"),
        lambda t: t.replace('description = "Says hello."', 'description = "<b>hi</b>"'),
        lambda t: t + 'surprise = "x"\n',
        lambda t: t.replace('run = "orch_hello"', 'run = "os.path"'),
    ],
)
def test_invalid_manifests_refused(tmp_path, mutate):
    folder = make_addon(tmp_path / "a", mutate=mutate)
    with pytest.raises(Refused):
        addons.folder_manifest(folder)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlink_and_remote_ref_refused(tmp_path):
    folder = make_addon(tmp_path / "a")
    pkg = folder / "src" / "orch_hello"
    outside = tmp_path / "secret.txt"
    outside.write_text("s", encoding="utf-8")
    (pkg / "skills" / "orch-hello" / "leak.md").symlink_to(outside)
    with pytest.raises(Refused, match="leaves"):
        addons.folder_manifest(folder)
    (pkg / "skills" / "orch-hello" / "leak.md").unlink()
    (pkg / "ext.schema.json").write_text('{"$ref": "https://evil.example/s.json"}', encoding="utf-8")
    with pytest.raises(Refused, match="remote"):
        addons.folder_manifest(folder)


def test_entry_point_must_match_manifest(tmp_path, monkeypatch):
    folder = make_addon(tmp_path / "a")
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setattr(
        addons, "_entry_points", lambda: {"other": "orch_hello", "os": "os", "ticket": "json"}
    )
    assert addons.discover() == {}


# ---- add / list / activation ------------------------------------------------------------------------


def test_add_needs_consent_then_installs_and_activates(proj, run, hello, uv_calls):
    code, _, err = run("addon", "add", str(hello))  # not a tty, no --yes
    assert code == 2 and "--yes" in err and not uv_calls
    assert not (proj / ".orch" / "addons.json").exists()
    code, out, err = run("addon", "add", str(hello), "--yes")
    assert code == 0, err
    assert "local folder (not checked by orch)" in out and "ext.hello" in out and "Hello" in out
    assert uv_calls[0][:3] == ["tool", "install", "--reinstall"] and uv_calls[0][-1] == str(hello.resolve())
    reg = json.loads((Path(os.environ["ORCH_HOME"]) / "addons.json").read_text(encoding="utf-8"))
    assert reg == [{"name": "hello", "source": str(hello.resolve()), "version": "0.1.0"}]
    act = json.loads((proj / ".orch" / "addons.json").read_text(encoding="utf-8"))["active"]
    assert list(act) == ["hello"] and act["hello"]["version"] == "0.1.0"
    assert (proj / ".agents/skills/orch-hello/SKILL.md").is_file()
    assert not (proj / ".agents/skills/orch-hello/AGENTS-block.md").exists()
    agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- orch:addon:hello -->\n## orch-hello" in agents and "<!-- /orch:addon:hello -->" in agents
    rows = json.loads(run("addon", "list", "--json")[1])
    assert rows == [
        {
            "name": "hello",
            "version": "0.1.0",
            "description": "Says hello.",
            "source": "local",
            "active": True,
            "dashboard": {"label": "Hello", "icon": "star", "order": 20},
            "ticket_view": [{"field": "greeting", "label": "Greeting", "format": "text"}],
            "background": False,
        }
    ]


def test_add_refuses_bad_sources(proj, run, uv_calls, tmp_path):
    for src in ("ticket", "Nope!", str(tmp_path / "missing" / "x"), "./nofolder"):
        code, _, err = run("addon", "add", src, "--yes")
        assert code == 2 and not uv_calls, src
    d = tmp_path / "empty"
    d.mkdir()
    (d / "pyproject.toml").write_text("", encoding="utf-8")
    assert run("addon", "add", str(d), "--yes")[0] == 2


def test_builtin_name_from_local_repo(proj, run, tmp_path, monkeypatch, uv_calls):
    repo = tmp_path / "repo"
    make_addon(repo / "workspace-addons")
    monkeypatch.setenv("ORCH_REPO", str(repo))
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    assert run("addon", "add", "nothere", "--yes")[0] == 2 and not uv_calls
    code, _, err = run("addon", "add", "hello", "--yes")  # installs, then the project step finds no package
    assert uv_calls and uv_calls[0][-1] == str((repo / "workspace-addons" / "hello").resolve())
    assert code == 2 and not (proj / ".orch" / "addons.json").exists()  # not installed -> never activated


def test_leftovers_never_activate(proj, run, hello, monkeypatch):
    # installed on the machine, but never turned on here; everything a leftover could be is present
    sys.path.insert(0, str(hello / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    addons._save_registry([{"name": "hello", "source": str(hello), "version": "0.1.0"}])
    try:
        (proj / ".orch" / "addons" / "hello").mkdir(parents=True)
        (proj / ".agents/skills/orch-hello").mkdir(parents=True)
        (proj / "AGENTS.md").write_text("<!-- orch:addon:hello -->\nx\n<!-- /orch:addon:hello -->\n")
        t = json.loads(run("ticket", "new", "T", "--json")[1])
        run("ext", "set", t["id"], "hello", '{"greeting": "hi"}')
        assert addons.active(proj) == {}
        code, _, err = run("hello", "x")
        assert code == 2 and "not turned on in this workspace. Turn it on: orch addon add hello" in err
        out = run("ticket", "show", t["id"], "--json")[1]
        assert "ext" not in json.loads(out) or json.loads(out)["ext"] == {}  # hidden while off
        code, out, _ = run("addon", "list", "--json")
        assert json.loads(out)[0]["active"] is False
        (proj / ".orch" / "addons.json").write_text("not json", encoding="utf-8")
        assert addons.active(proj) == {}
        (proj / ".orch" / "addons.json").write_text('{"active": {"../x": {}, "ok": 5, "hello": {}}}')
        assert list(addons.listed(proj)) == ["hello"] and addons.active(proj) == {}  # listed is not on
    finally:
        sys.path.remove(str(hello / "src"))


def test_active_but_not_installed_is_refused(proj, run):
    (proj / ".orch").mkdir()
    (proj / ".orch" / "addons.json").write_text('{"active": {"ghost": {"version": "1.0.0"}}}')
    addons.record_consent(proj, "ghost")
    code, _, err = run("ghost")
    assert code == 2 and "not installed" in err


# ---- dispatch ---------------------------------------------------------------------------------------


def test_dispatch_runs_subprocess_with_env(proj, run, hello):
    install(run, hello)
    code, out, _ = run("hello", "greet", "--json", "x")
    assert code == 0
    got = json.loads(out)
    assert got["argv"] == ["greet", "--json", "x"] and got["addon"] == "hello" and got["bin"]
    assert Path(got["root"]).resolve() == proj.resolve() and Path(got["cwd"]).resolve() == proj.resolve()
    assert run("hello", "fail")[0] == 3  # exit codes pass through


def test_dispatch_does_not_import_from_workspace(proj, run, hello):
    install(run, hello)
    (proj / "orch_hello.py").write_text("raise SystemExit(9)", encoding="utf-8")
    assert run("hello", "greet")[0] == 0


def test_unknown_command_is_usage_error(proj, run):
    with pytest.raises(SystemExit) as e:
        cli.main(["nonesuch"])
    assert e.value.code == 2


def test_not_on_error_json(proj, run, hello):
    install(run, hello)
    run("addon", "remove", "hello")
    code, out, err = run("hello", "view", "--json")
    assert code == 2 and json.loads(out)["error"].startswith("The hello add-on is not turned on")


def test_help_lists_active_addons_only(proj, run, hello, capfd):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "Add-ons:" not in capfd.readouterr().out
    install(run, hello)
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = capfd.readouterr().out
    assert "Add-ons:\n  hello       Says hello." in text and "More commands" in text


# ---- remove -----------------------------------------------------------------------------------------


def test_remove_keeps_data_and_text_outside_block(proj, run, hello):
    (proj / "AGENTS.md").write_text("# Mine\nhello\n", encoding="utf-8")
    install(run, hello)
    (proj / ".agents/skills/orch-hello-extra").mkdir()
    (proj / ".agents/skills/orch-hellox").mkdir()  # not ours (different name)
    (proj / ".orch/addons/hello").mkdir(parents=True)
    (proj / ".orch/addons/hello/state.json").write_text("{}", encoding="utf-8")
    tid = json.loads(run("ticket", "new", "T", "--json")[1])["id"]
    assert run("ext", "set", tid, "hello", '{"greeting": "hi"}')[0] == 0
    agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
    (proj / "AGENTS.md").write_text(agents + "\nTail text\n", encoding="utf-8")
    assert run("addon", "remove", "hello")[0] == 0
    assert not (proj / ".agents/skills/orch-hello").exists()
    assert (proj / ".agents/skills/orch-hello-extra").exists()  # exact name only
    assert (proj / ".agents/skills/orch-hellox").exists()
    text = (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert "orch:addon" not in text and text.startswith("# Mine\nhello\n") and "Tail text" in text
    assert addons.active(proj) == {}
    assert (proj / ".orch/addons/hello/state.json").is_file()
    ticket = json.loads((proj / ".orch/tickets" / f"{tid}.json").read_text(encoding="utf-8"))
    assert ticket["ext"]["hello"] == {"greeting": "hi"}  # kept in the file ...
    shown = json.loads(run("ticket", "show", tid, "--json")[1])
    assert "hello" not in shown.get("ext", {})  # ... hidden while off
    assert json.loads(run("ticket", "list", "--json")[1])[0].get("ext", {}) == {}
    assert run("addon", "remove", "hello")[0] == 2  # not on any more


def test_remove_stops_background_process(proj, run, tmp_path, monkeypatch, uv_calls):
    folder = make_addon(tmp_path / "b", bg=True)
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    install(run, folder)
    assert run("addon", "remove", "hello")[0] == 0
    assert (proj / "stopped.txt").read_text(encoding="utf-8") == "stopped"


def test_purge_deletes_data_and_config_table_only(proj, run, hello):
    install(run, hello)
    (proj / ".orch/addons/hello").mkdir(parents=True)
    (proj / ".orch/addons/hello/state.json").write_text("{}", encoding="utf-8")
    (proj / ".orch/config.toml").write_text(
        textwrap.dedent("""\
        [relay]
        x = 1

        [hello]
        a = 1
        [hello.sub]
        b = 2

        [hello2]
        keep = true
        """),
        encoding="utf-8",
    )
    assert run("addon", "remove", "hello", "--purge")[0] == 0
    assert not (proj / ".orch/addons/hello").exists()
    cfg = (proj / ".orch/config.toml").read_text(encoding="utf-8")
    assert "[relay]" in cfg and "[hello2]" in cfg and "[hello]" not in cfg and "sub" not in cfg


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_purge_refuses_links(proj, run, hello, tmp_path):
    install(run, hello)
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "f.txt").write_text("keep", encoding="utf-8")
    ad = proj / ".orch/addons"
    ad.mkdir(parents=True, exist_ok=True)
    # 1. the add-on folder is a link out
    (ad / "hello").symlink_to(outside, target_is_directory=True)
    assert run("addon", "remove", "hello", "--purge")[0] == 2
    assert (outside / "f.txt").read_text(encoding="utf-8") == "keep"
    assert "hello" in addons.listed(proj)  # nothing was changed
    (ad / "hello").unlink()
    # 2. a link inside the folder points out
    (ad / "hello").mkdir()
    (ad / "hello" / "leak").symlink_to(outside, target_is_directory=True)
    assert run("addon", "remove", "hello", "--purge")[0] == 2
    assert (outside / "f.txt").is_file() and (ad / "hello").is_dir()
    (ad / "hello" / "leak").unlink()
    # 3. .orch/addons is a link out
    (ad / "hello").rmdir()
    ad.rmdir()
    ad.symlink_to(outside, target_is_directory=True)
    assert run("addon", "remove", "hello", "--purge")[0] == 2
    assert (outside / "f.txt").is_file()
    ad.unlink()
    # 4. .orch itself is a link out
    moved = tmp_path / "moved-orch"
    (proj / ".orch").rename(moved)
    (proj / ".orch").symlink_to(moved, target_is_directory=True)
    (outside / "addons").mkdir()
    assert run("addon", "remove", "hello", "--purge")[0] == 2
    assert (outside / "f.txt").is_file()


# ---- consent on this machine ------------------------------------------------------------------------


def test_addons_json_from_git_alone_never_activates(proj, run, hello, tmp_path):
    install(run, hello)
    listing = (proj / ".orch/addons.json").read_text(encoding="utf-8")
    # a fresh machine: same workspace files arrive by git clone, but there is no consent record here
    Path(os.environ["ORCH_HOME"], "consent.json").unlink()
    assert (proj / ".orch/addons.json").read_text(encoding="utf-8") == listing
    assert addons.active(proj) == {} and list(addons.listed(proj)) == ["hello"]
    code, _, err = run("hello", "greet")
    assert (
        code == 2
        and "listed for this workspace but not turned on here. Turn it on: orch addon add hello" in err
    )
    assert (
        run("addon", "list", "--json")[1]
        and json.loads(run("addon", "list", "--json")[1])[0]["active"] is False
    )
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    # nothing is refreshed or started by update, and the project step alone cannot turn it on
    (proj / ".agents/skills/orch-hello/SKILL.md").write_text("mine", encoding="utf-8")
    assert run("update")[0] == 0
    assert (proj / ".agents/skills/orch-hello/SKILL.md").read_text(encoding="utf-8") == "mine"
    assert run("addon", "add", "hello", "--project-only")[0] == 2
    # the user turns it on here: now it works
    assert run("addon", "add", str(hello), "--yes")[0] == 0
    assert run("hello", "greet")[0] == 0


def test_consent_is_tied_to_workspace_and_folder_content(proj, run, hello, tmp_path):
    install(run, hello)
    rec = json.loads(Path(os.environ["ORCH_HOME"], "consent.json").read_text(encoding="utf-8"))[0]
    assert rec["workspace"] == str(proj.resolve()) and rec["name"] == "hello"
    assert rec["path"] == str(hello.resolve()) and len(rec["hash"]) == 64
    assert run("hello", "greet")[0] == 0
    # the local folder changed after the user agreed: not on until they agree again
    (hello / "src/orch_hello/__main__.py").write_text("print('evil')\n", encoding="utf-8")
    code, _, err = run("hello", "greet")
    assert code == 2 and "not turned on" in err
    assert run("addon", "add", str(hello), "--yes")[0] == 0
    assert run("hello", "greet")[0] == 0
    # a copy of the workspace somewhere else has no consent
    other = tmp_path / "copy"
    other.mkdir()
    (other / ".orch").mkdir()
    (other / ".orch/addons.json").write_text((proj / ".orch/addons.json").read_text(encoding="utf-8"))
    assert addons.active(other) == {}


def test_builtin_also_needs_local_record(proj, run, tmp_path, monkeypatch):
    (proj / ".orch").mkdir()
    (proj / ".orch/addons.json").write_text('{"active": {"scheduler": {"version": "0.2.0"}}}')
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    assert addons.active(proj) == {}
    addons.record_consent(proj, "scheduler")  # built-in: no registry entry = built-in
    assert list(addons.active(proj)) == ["scheduler"]


def test_remove_rejects_path_names(proj, run):
    assert run("addon", "remove", "../x")[0] == 2


# ---- AGENTS block markers ---------------------------------------------------------------------------


def test_block_only_between_markers(proj, run, hello):
    run("init")
    agents = proj / "AGENTS.md"
    agents.write_text("Before\n" + agents.read_text(encoding="utf-8") + "After\n", encoding="utf-8")
    install(run, hello)
    first = agents.read_text(encoding="utf-8")
    assert first.startswith("Before\n") and first.count("<!-- orch:addon:hello -->") == 1
    (hello / "src/orch_hello/skills/orch-hello/AGENTS-block.md").write_text(
        "## orch-hello\n<!-- /orch:addon:hello -->\nNEW\n<!-- orch:begin orch -->\n", encoding="utf-8"
    )
    run("addon", "add", str(hello), "--yes")  # again: replaced whole, body cannot bring markers
    second = agents.read_text(encoding="utf-8")
    assert second.count("<!-- orch:addon:hello -->") == 1 and second.count("<!-- /orch:addon:hello -->") == 1
    assert second.count("<!-- orch:begin orch -->") == 1 and "NEW" in second and "Before" in second


# ---- ext schema check -------------------------------------------------------------------------------


def test_ext_checked_only_while_active(proj, run, hello):
    tid = json.loads(run("ticket", "new", "T", "--json")[1])["id"]
    assert run("ext", "set", tid, "hello", '{"anything": 1}')[0] == 0  # not active: unchecked
    install(run, hello)
    code, _, err = run("ext", "set", tid, "hello", '{"greeting": "far too long"}')
    assert code == 2 and "ext.hello" in err
    assert run("ext", "set", tid, "hello", '{"greeting": "hi"}')[0] == 2  # merged with {"anything": 1}
    t2 = json.loads(run("ticket", "new", "T2", "--json")[1])["id"]
    assert run("ext", "set", t2, "hello", '{"greeting": "hi"}', "--json")[0] == 0


def test_ext_set_if_revision(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ext", "set", tid, "other", '{"a": 1}', "--if-revision", "5")[0] == 2
    code, out, _ = run("ext", "set", tid, "other", '{"a": 1}', "--if-revision", "1", "--json")
    assert code == 0
    assert run("ext", "set", tid, "other", '{"a": 2}', "--if-revision", "1")[0] == 2


# ---- update / uninstall -----------------------------------------------------------------------------


def test_update_reinstalls_all_and_refreshes_active(proj, run, hello, uv_calls):
    run("init")
    install(run, hello)
    uv_calls.clear()
    (proj / ".agents/skills/orch/SKILL.md").write_text("stale", encoding="utf-8")
    (proj / ".agents/skills/orch-hello/SKILL.md").write_text("stale", encoding="utf-8")
    assert run("update")[0] == 0
    assert len(uv_calls) == 1 and uv_calls[0][-2:] == ["--with", str(hello.resolve())]
    assert "name: orch" in (proj / ".agents/skills/orch/SKILL.md").read_text(encoding="utf-8")
    assert "name: orch-hello" in (proj / ".agents/skills/orch-hello/SKILL.md").read_text(encoding="utf-8")


def test_update_does_not_activate_installed_addons(proj, run, hello, uv_calls):
    run("init")
    install(run, hello)
    run("addon", "remove", "hello")
    assert run("update")[0] == 0
    assert addons.active(proj) == {} and not (proj / ".agents/skills/orch-hello").exists()


def test_uninstall(proj, run, hello, uv_calls):
    install(run, hello)
    assert run("addon", "uninstall", "hello")[0] == 2  # still on here
    run("addon", "remove", "hello")
    uv_calls.clear()
    assert run("addon", "uninstall", "hello")[0] == 0
    assert "--with" not in uv_calls[0] and addons.registry() == []
    assert run("addon", "uninstall", "hello")[0] == 2


# ---- core knows no add-on --------------------------------------------------------------------------


def test_core_text_names_no_addon():
    root = Path(__file__).resolve().parents[1]
    words = ("scheduler", "wake_at", "recurring")
    files = [p for p in (root / "skills").rglob("*") if p.is_file()]
    files += [p for p in (root / "src" / "orch").glob("*.py") if p.name != "addons.py"]
    for p in files:
        low = p.read_text(encoding="utf-8").lower()
        for w in words:
            assert w not in low, f"{p.name} mentions {w}"


def test_relay_status(proj, run, rel):
    code, out, _ = run("relay", "status", "--json")
    assert code == 0 and json.loads(out) == {"configured": False}


# ---- security review 3 ------------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows cannot create a folder named https:, so the attack is impossible there",
)
def test_default_repo_is_never_a_folder(proj, monkeypatch):
    monkeypatch.delenv("ORCH_REPO", raising=False)
    planted = proj / "https:" / "github.com" / "severinlindenmann" / "orch"
    planted.mkdir(parents=True)
    assert not addons._is_local(addons.DEFAULT_REPO)
    assert addons.spec("workspace").startswith("git+https://github.com/severinlindenmann/orch@")
    monkeypatch.setenv("ORCH_REPO", "relative/dir")  # relative: not local either
    (proj / "relative" / "dir").mkdir(parents=True)
    assert not addons._is_local("relative/dir")
    monkeypatch.setenv("ORCH_REPO", str(proj))
    assert addons._is_local(str(proj))


def test_duplicate_entry_point_names_disable_both(tmp_path, monkeypatch):
    a = make_addon(tmp_path / "a")
    monkeypatch.syspath_prepend(str(a / "src"))
    addons._save_registry([{"name": "hello", "source": str(a), "version": "0.1.0"}])
    monkeypatch.setattr(addons, "_entry_points", lambda: [("hello", "orch_hello"), ("hello", "orch_evil")])
    assert addons.discover() == {}
    monkeypatch.setattr(addons, "_entry_points", lambda: [("hello", "orch_hello")])
    assert list(addons.discover()) == ["hello"]
    # an entry point the user never installed through orch does not count
    addons._save_registry([])
    assert addons.discover() == {}


def test_agents_block_cannot_forge_markers(tmp_path):
    from orch import skills

    root = tmp_path
    for body in (
        "x <!-- /orch:add<!-- orch:end y -->on:foo --> tail",
        "x <!-- orch:be<!-- orch:end y -->gin orch --> tail",
        "x <!--orch:end orch --> tail",
        "x <!-- orch:end orch tail",
    ):
        try:
            skills.set_block(root, "foo", body, addon=True)
        except Refused:
            continue
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        assert text.count("<!-- orch:addon:foo -->") == 1 and "<!-- /orch:addon:foo -->" in text
        assert text.count("<!--") == 2, text  # only our two markers remain
        skills.remove_block(root, "foo", addon=True)
        assert not (root / "AGENTS.md").read_text(encoding="utf-8").strip()


def test_orch_home_must_be_plain_folder_under_home(proj, monkeypatch, capfd):
    h = addons.real_home()
    real = h / ".orch-tool"
    for bad in (
        proj / "shipped",
        proj.parent / "elsewhere",
        h.parent,
    ):  # in project / outside home / above home
        monkeypatch.setenv("ORCH_HOME", str(bad))
        assert addons.home() == real
    assert "ignored" in capfd.readouterr().err
    # an ancestor between ORCH_HOME and home holds .git / .orch / .agents (a repo aiming at its parent)
    for marker in (".git", ".orch", ".agents"):
        repo = h / f"repo-{marker[1:]}"
        (repo / marker).mkdir(parents=True)
        monkeypatch.setenv("ORCH_HOME", str(repo / "sub" / "home"))
        assert addons.home() == real, marker
    monkeypatch.setenv("HOME", str(proj / "fakehome"))  # $HOME is not what counts
    assert addons.real_home() == h
    ok = h / "cfg" / "orchhome"
    monkeypatch.setenv("ORCH_HOME", str(ok))
    assert addons.home() == ok.resolve()


def test_folder_hash_skips_build_only_at_top_level(tmp_path):
    f = tmp_path / "addon"
    (f / "build").mkdir(parents=True)
    (f / "src" / "pkg" / "build").mkdir(parents=True)
    (f / "build" / "junk.py").write_text("1", encoding="utf-8")
    (f / "src" / "pkg" / "build" / "x.py").write_text("1", encoding="utf-8")
    h1 = addons.folder_hash(f)
    (f / "build" / "junk.py").write_text("2", encoding="utf-8")
    assert addons.folder_hash(f) == h1  # top-level build output is ignored
    (f / "src" / "pkg" / "build" / "x.py").write_text("2", encoding="utf-8")
    assert addons.folder_hash(f) != h1  # code in a nested build/ folder counts


def test_consent_bound_to_workspace_id(proj, run, hello):
    install(run, hello)
    wid = (proj / ".orch/.local-id").read_text(encoding="utf-8").strip()
    assert len(wid) == 32
    assert run("hello", "greet")[0] == 0
    (proj / ".orch/.local-id").unlink()  # clone/copy: no id -> consent needed again
    assert addons.active(proj) == {}
    assert run("hello", "greet")[0] == 2
    (proj / ".orch/.local-id").write_text("0" * 32, encoding="utf-8")  # a forged id has no record
    assert addons.active(proj) == {}
    assert run("addon", "add", str(hello), "--yes")[0] == 0
    assert run("hello", "greet")[0] == 0


def test_consent_records_of_deleted_workspaces_are_pruned(proj, run, hello, tmp_path):
    install(run, hello)
    cp = addons.consent_path()
    recs = json.loads(cp.read_text(encoding="utf-8"))
    recs.append({"workspace_id": "a" * 32, "workspace": str(tmp_path / "gone"), "name": "hello"})
    cp.write_text(json.dumps(recs), encoding="utf-8")
    addons.record_consent(proj, "hello")
    left = json.loads(cp.read_text(encoding="utf-8"))
    assert [r["workspace"] for r in left] == [str(proj.resolve())]


def test_update_does_not_reaccept_changed_local_folder(proj, run, hello, uv_calls):
    run("init")
    install(run, hello)
    (hello / "src/orch_hello/__main__.py").write_text("print('changed')\n", encoding="utf-8")
    (proj / ".agents/skills/orch-hello/SKILL.md").write_text("mine", encoding="utf-8")
    code, _, err = run("update")
    assert code == 0 and "changed on disk" in err
    assert (proj / ".agents/skills/orch-hello/SKILL.md").read_text(encoding="utf-8") == "mine"
    assert run("hello", "greet")[0] == 2  # still off until the user agrees again


def test_stale_lock_is_claimed_by_one_waiter_only(proj, new_ticket):
    import os

    from orch import tickets

    tid = new_ticket()
    lock = proj / ".orch" / "tickets" / f".lock-{tid}"
    lock.write_text("", encoding="utf-8")
    old = lock.stat().st_mtime - 120
    os.utime(lock, (old, old))
    assert tickets._break_stale(lock) is True and not lock.exists()
    assert tickets._break_stale(lock) is False  # second waiter finds nothing to take
    lock.write_text("", encoding="utf-8")  # a fresh lock someone else holds is put back, not broken
    assert tickets._break_stale(lock) is False and lock.exists()


# ---- owner bugs 5 Nov: built-in add-on from a git install ------------------------------------------


def test_builtin_add_asks_on_a_tty_and_shows_what_it_adds(proj, run, tmp_path, monkeypatch, uv_calls):
    """Bug A: `orch addon add dashboard` in a terminal shows the add-on and asks, instead of refusing."""
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.setattr(addons, "_install_origin", lambda: {})
    folder = make_addon(tmp_path / "pv")
    seen = []
    monkeypatch.setattr(addons, "preview_builtin", lambda n: seen.append(n) or addons.folder_manifest(folder))
    monkeypatch.setattr(addons, "_entry_points", lambda: {})

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty("n\n"))
    code, _, err = run("addon", "add", "hello")
    assert code == 2 and seen == ["hello"] and "Adds a dashboard tab: Hello" in err and "Add it? [y/N]" in err
    assert "Not confirmed" in err and not uv_calls
    monkeypatch.setattr(sys, "stdin", Tty("y\n"))
    run("addon", "add", "hello")
    assert uv_calls and uv_calls[0][-1].endswith("#subdirectory=workspace-addons/hello")
    reg = json.loads((Path(os.environ["ORCH_HOME"]) / "addons.json").read_text(encoding="utf-8"))
    assert reg == [{"name": "hello", "source": "built-in", "version": "0.1.0"}]
    # not a terminal (agents, CI): refused with the hint, nothing fetched
    seen.clear()
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code, _, err = run("addon", "add", "other")
    assert code == 2 and "--yes" in err and not seen


def test_addons_install_from_where_orch_came_from(proj, monkeypatch, uv_calls):
    """Bug B: installed with ORCH_REF=develop, `orch addon add` must not reinstall orch from main (that
    downgraded orch and fed the new registry entries to the old code as package names)."""
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.delenv("ORCH_REF", raising=False)
    monkeypatch.setattr(
        addons, "_install_origin", lambda: {"repo": "https://github.com/someone/orch", "ref": "develop"}
    )
    addons._save_registry([{"name": "dashboard", "source": "built-in", "version": "0.0.0"}])
    addons._install_tool(
        addons.registry() + [{"name": "scheduler", "source": "built-in", "version": "0.0.0"}]
    )
    args = uv_calls[0]
    assert all(isinstance(a, str) for a in args)
    assert args[3] == "git+https://github.com/someone/orch@develop#subdirectory=workspace"
    assert args[4:] == [
        "--with",
        "git+https://github.com/someone/orch@develop#subdirectory=workspace-addons/dashboard",
        "--with",
        "git+https://github.com/someone/orch@develop#subdirectory=workspace-addons/scheduler",
    ]
    monkeypatch.setenv("ORCH_REF", "v1")  # an explicit override still wins
    assert addons.spec("workspace").endswith("@v1#subdirectory=workspace")


def test_install_origin_reads_direct_url(monkeypatch, tmp_path):
    import importlib.metadata as md

    class D:
        def __init__(self, data):
            self.data = data

        def read_text(self, _):
            return json.dumps(self.data)

    cases = [
        (
            {
                "url": "https://github.com/a/orch",
                "subdirectory": "workspace",
                "vcs_info": {"vcs": "git", "requested_revision": "develop", "commit_id": "abc"},
            },
            {"repo": "https://github.com/a/orch", "ref": "develop"},
        ),
        ({"url": (tmp_path / "workspace").as_uri(), "dir_info": {}}, {"repo": str(tmp_path), "local": True}),
        ({"url": (tmp_path / "workspace").as_uri(), "dir_info": {"editable": True}}, {}),
        ({"url": "https://x/y.whl", "archive_info": {}}, {}),
    ]
    for data, want in cases:
        monkeypatch.setattr(md, "distribution", lambda _n, d=data: D(d))
        assert addons._install_origin() == want
