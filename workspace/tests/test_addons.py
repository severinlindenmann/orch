import io
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from orch import addons, cli, tickets
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


def third_party() -> dict:
    """discover() without the built-in publish and relay add-ons (always there)."""
    return {k: v for k, v in addons.discover().items() if k not in addons.CORE_ADDONS}


def install(run, folder):
    code, out, err = run("addon", "add", str(folder), "--yes")
    assert code == 0, err


# ---- discovery and manifest -------------------------------------------------------------------------


def test_discovery_never_imports_addon_code(tmp_path, monkeypatch):
    folder = make_addon(tmp_path / "a")
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    addons._save_registry([{"name": "hello", "source": str(folder), "version": "0.1.0"}])
    found = third_party()
    assert list(found) == ["hello"] and found["hello"]["version"] == "0.1.0"
    assert not (tmp_path / "a" / "IMPORTED-hello").exists()
    assert "orch_hello" not in sys.modules


def test_discovery_test_never_reaches_the_real_home(tmp_path, monkeypatch):
    """Regression (9 Nov): the registry a discovery test writes lands in the faked home, never in the
    account's real ~/.orch-tool (the harness fakes real_home, ORCH_HOME, HOME and sets ORCH_HOME_STRICT)."""
    import conftest

    assert addons.real_home is not conftest._REAL_HOME_FN
    fake = addons.real_home()
    assert os.environ["ORCH_HOME_STRICT"] == "1" and Path(os.environ["HOME"]) == fake
    assert Path(os.environ["ORCH_HOME"]).resolve().is_relative_to(fake.resolve())
    folder = make_addon(tmp_path / "a")
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    addons._save_registry([{"name": "hello", "source": str(folder), "version": "0.1.0"}])
    reg = Path(os.environ["ORCH_HOME"]) / "addons.json"
    assert reg.is_file() and addons.registry_path() == reg.resolve()
    assert list(third_party()) == ["hello"]
    assert addons.registry_path().resolve() != (conftest._REAL_HOME_FN() / ".orch-tool" / "addons.json")


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
    assert third_party() == {}


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
    agents = (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    assert "## orch-hello" in agents and not (proj / "AGENTS.md").exists()  # the team's files are not touched
    rows = [r for r in json.loads(run("addon", "list", "--json")[1]) if r["name"] not in addons.CORE_ADDONS]
    assert rows == [
        {
            "name": "hello",
            "version": "0.1.0",
            "description": "Says hello.",
            "source": "local",
            "installed": True,
            "active": True,
            "dashboard": {"label": "Hello", "icon": "star", "order": 20},
            "ticket_view": [{"field": "greeting", "label": "Greeting", "format": "text"}],
            "background": False,
            "recommended": False,
            "page": None,
            "running": False,
            "ticket_links": [],
            "ticket_fields": None,
            "acts": [],
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
    assert text == agents + "\nTail text\n" and text.startswith("# Mine\nhello\n")  # never edited by orch
    assert not (proj / ".orch/harness/AGENTS.orch.md").exists()  # the only block was hello's
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
    (proj / ".orch/addons.json").write_text('{"active": {"focus": {"version": "0.2.0"}}}')
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    assert addons.active(proj) == {}
    addons.record_consent(proj, "focus")  # built-in: no registry entry = built-in
    assert list(addons.active(proj)) == ["focus"]


def test_remove_rejects_path_names(proj, run):
    assert run("addon", "remove", "../x")[0] == 2


# ---- AGENTS block markers ---------------------------------------------------------------------------


def test_block_cannot_bring_markers_and_agents_md_is_not_touched(proj, run, hello):
    run("init")
    (proj / "AGENTS.md").write_text("Before\n", encoding="utf-8")
    install(run, hello)
    block = proj / ".orch/harness/AGENTS.orch.md"
    assert block.read_text(encoding="utf-8").count("## orch-hello") == 1
    (hello / "src/orch_hello/skills/orch-hello/AGENTS-block.md").write_text(
        "## orch-hello\n<!-- /orch:addon:hello -->\nNEW\n<!-- orch:begin orch -->\n", encoding="utf-8"
    )
    run("addon", "add", str(hello), "--yes")  # again: replaced whole, body cannot bring markers
    text = block.read_text(encoding="utf-8")
    assert text.count("## orch-hello") == 1 and "<!--" not in text and "NEW" in text
    assert (proj / "AGENTS.md").read_text(encoding="utf-8") == "Before\n"


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
    assert addons.spec("workspace").startswith("https://github.com/severinlindenmann/orch/archive/")
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
    assert third_party() == {}
    monkeypatch.setattr(addons, "_entry_points", lambda: [("hello", "orch_hello")])
    assert list(third_party()) == ["hello"]
    # an entry point the user never installed through orch does not count
    addons._save_registry([])
    assert third_party() == {}


def test_agents_block_cannot_forge_markers(tmp_path):
    from orch import skills

    root = tmp_path
    for body in (
        "x <!-- /orch:add<!-- orch:end y -->on:foo --> tail",
        "x <!-- orch:be<!-- orch:end y -->gin orch --> tail",
        "x <!--orch:end orch --> tail",
        "x <!-- orch:end orch tail",
    ):
        skills.set_block(root, "foo", body, addon=True)
        text = (root / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
        assert "<!--" not in text and "-->" not in text, text  # no comment, so no marker, survives
        skills.remove_block(root, "foo", addon=True)
        assert not (root / ".orch/harness/AGENTS.orch.md").exists() and not (root / "AGENTS.md").exists()


def test_orch_home_must_be_plain_folder_under_home(proj, monkeypatch, capfd):
    monkeypatch.delenv("ORCH_HOME_STRICT")  # the old, non-strict fallback
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


def test_strict_untrusted_orch_home_is_an_error_and_writes_nothing(proj, run, monkeypatch):
    h = addons.real_home()
    real = h / ".orch-tool"
    (h / "repo" / ".git").mkdir(parents=True)  # a temp home inside a git repo
    for bad in (h / "repo" / "home", proj / "inside-cwd"):
        monkeypatch.setenv("ORCH_HOME", str(bad))
        monkeypatch.setenv("ORCH_HOME_STRICT", "1")
        seen = sorted(real.rglob("*")) if real.exists() else None
        with pytest.raises(Refused, match="ORCH_HOME_STRICT"):
            addons.home()
        code, out, err = run("addon", "list")
        assert code != 0 and "ORCH_HOME_STRICT" in err and str(bad) in err
        assert (sorted(real.rglob("*")) if real.exists() else None) == seen and not bad.exists()
        # without the switch the old fallback stays (a note, then the real folder)
        monkeypatch.delenv("ORCH_HOME_STRICT")
        assert addons.home() == real
    assert not real.exists() or not any(real.rglob("*"))  # the fallback writes nothing there (non-strict)


def test_strict_cwd_above_the_home_is_an_error(proj, monkeypatch):
    """A teardown started with the user's home as its folder made every home 'inside the current folder'."""
    h = addons.real_home()
    monkeypatch.chdir(h)
    monkeypatch.setenv("ORCH_HOME", str(h / "cfg" / "orchhome"))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    with pytest.raises(Refused):
        addons.home()
    with pytest.raises(Refused):
        addons._save_registry([])
    assert not (h / ".orch-tool").exists() and not (h / "cfg").exists()


def test_trusted_orch_home_never_touches_the_real_tool_folder(proj, run, monkeypatch):
    """Registry, consent, running.json and the stop/status paths all use the trusted home only."""
    h = addons.real_home()
    ok = h / "cfg" / "orchhome"
    monkeypatch.setenv("ORCH_HOME", str(ok))
    (proj / ".orch").mkdir()
    addons._save_registry([])
    for argv in (("addon", "list"), ("stop", "--all"), ("stop"), ("status")):
        run(*([argv] if isinstance(argv, str) else argv))
    from orch import services

    assert services.stop(proj) is not None
    assert services.status() == []
    assert not (h / ".orch-tool").exists()
    assert (ok / "addons.json").exists()


def _trace_lines(h):
    f = addons._trace_log_path()  # the harness points it at a per-test file outside the faked real home
    assert not f.resolve().is_relative_to(h.resolve())
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def _trace_on(monkeypatch):
    monkeypatch.setenv("ORCH_TRACE_FALLBACKS", "1")  # the only opt-in: nothing in the real home turns it on


def test_fallback_trace_is_off_without_the_env_switch(proj, monkeypatch):
    h = addons.real_home()
    monkeypatch.delenv("ORCH_HOME")
    monkeypatch.delenv("ORCH_HOME_STRICT")
    for value in (None, "", "0"):
        if value is None:
            monkeypatch.delenv("ORCH_TRACE_FALLBACKS", raising=False)
        else:
            monkeypatch.setenv("ORCH_TRACE_FALLBACKS", value)
        assert addons.home() == h / ".orch-tool"
        assert not (h / ".orch-tool").exists()  # a normal install: home() only reads
        assert not addons._trace_log_path().exists()


def test_fallback_trace_marker_file_in_the_real_home_has_no_effect(proj, monkeypatch, capsys):
    """#519: the old opt-in (~/.orch-tool/.trace-fallbacks) is gone: a marker there turns nothing on, and with
    the env switch on the trace is the same with or without it; the marker is left as it was."""
    h = addons.real_home()
    monkeypatch.delenv("ORCH_HOME")
    monkeypatch.delenv("ORCH_HOME_STRICT")
    (h / ".orch-tool").mkdir()
    (h / ".orch-tool" / ".trace-fallbacks").write_text("1", encoding="utf-8")
    before = _listing(h)
    assert addons.home() == h / ".orch-tool"
    assert not addons._trace_log_path().exists()
    assert _listing(h) == before
    assert capsys.readouterr().err == ""
    _trace_on(monkeypatch)
    assert addons.home() == h / ".orch-tool"
    assert [x["reason"] for x in _trace_lines(h)] == ["unset"]
    assert _listing(h) == before
    assert (h / ".orch-tool" / ".trace-fallbacks").read_text(encoding="utf-8") == "1"


def test_fallback_trace_file_lives_in_the_temp_folder_per_user():
    import tempfile

    import conftest

    p = conftest._TRACE_LOG  # the unpatched path, as orch computes it
    assert p.parent == Path(tempfile.gettempdir())
    assert p.name.startswith("orch-fallback-trace-") and p.name.endswith(".log")
    if hasattr(os, "getuid"):
        assert p.name == f"orch-fallback-trace-{os.getuid()}.log"


def _listing(d):
    return {str(p.relative_to(d)): (p.is_symlink(), p.lstat().st_mtime_ns) for p in (d, *d.rglob("*"))}


def test_fallback_trace_never_writes_into_the_real_home(proj, monkeypatch, tmp_path_factory):
    """#519: HOME and ORCH_HOME aimed at a symlinked temp folder make home() fall back to the real folder;
    with ORCH_TRACE_FALLBACKS on, the trace goes to the temp trace file and nothing under the real home is
    made or changed."""
    h = addons.real_home()
    _trace_on(monkeypatch)
    target = tmp_path_factory.mktemp("tmplike")
    link = tmp_path_factory.mktemp("links") / "home"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("HOME", str(link))
    monkeypatch.setenv("ORCH_HOME", str(link))
    monkeypatch.delenv("ORCH_HOME_STRICT")
    before = _listing(h)
    assert addons.home() == h / ".orch-tool"
    monkeypatch.delenv("ORCH_HOME")
    assert addons.home() == h / ".orch-tool"
    assert _listing(h) == before  # no new file, no rotation, no touched folder
    assert not (h / ".orch-tool").exists()
    assert [x["reason"] for x in _trace_lines(h)] == ["untrusted:outside-home", "unset"]
    assert addons._trace_log_path().stat().st_mode & 0o777 == 0o600
    assert list(target.iterdir()) == []


def test_fallback_trace_is_off_when_the_temp_folder_is_inside_the_real_home(proj, monkeypatch):
    h = addons.real_home()
    _trace_on(monkeypatch)
    monkeypatch.delenv("ORCH_HOME")
    monkeypatch.delenv("ORCH_HOME_STRICT")
    (h / "tmp").mkdir()
    monkeypatch.setattr(addons, "_trace_log_path", lambda: h / "tmp" / "orch-fallback-trace.log")
    before = _listing(h)
    assert addons.home() == h / ".orch-tool"
    assert _listing(h) == before


def test_fallback_trace_logs_only_real_subcommands_and_never_blocks(proj, monkeypatch):
    h = addons.real_home()
    _trace_on(monkeypatch)
    monkeypatch.delenv("ORCH_HOME")
    monkeypatch.delenv("ORCH_HOME_STRICT")
    for argv, cmd in (
        (["orch", "sk-abc123def", "hunter2"], "orch"),  # word-shaped secrets are not subcommands
        (["orch", "addon", "sk-abc"], "orch addon"),
        (["pytest", "addon", "list"], "pytest addon list"),
    ):
        monkeypatch.setattr(sys, "argv", argv)
        addons.home()
        assert _trace_lines(h)[-1]["cmd"] == cmd
    if not hasattr(os, "mkfifo"):
        return
    log = addons._trace_log_path()
    log.unlink()
    os.mkfifo(log)  # nobody reads it: a blocking open would hang every orch command
    assert addons.home() == h / ".orch-tool"


def test_fallback_trace_unset_has_the_fields_and_never_argument_values(proj, monkeypatch):
    h = addons.real_home()
    _trace_on(monkeypatch)
    monkeypatch.delenv("ORCH_HOME")
    monkeypatch.delenv("ORCH_HOME_STRICT")
    monkeypatch.setattr(
        sys,
        "argv",
        ["/x/bin/orch", "addon", "list", "--token", "orn_secret123", "ghp_abc", "Pay Müller 4711"],
    )
    assert addons.home() == h / ".orch-tool"
    (line,) = _trace_lines(h)
    assert set(line) == {"time", "pid", "ppid", "cmd", "cwd", "reason"}
    assert line["reason"] == "unset" and line["pid"] == os.getpid() and line["cwd"] == os.getcwd()
    assert line["cmd"] == "orch addon list"
    mode = addons._trace_log_path().stat().st_mode & 0o777
    assert mode == 0o600
    for argv, cmd in (
        (["orch", "ticket", "new", "--token", "orn_x"], "orch ticket new"),  # two words at most
        (["orch", "--token=ghp_x", "list"], "orch"),  # stops at the first option
        (["orch", "Fix the bug", "x"], "orch"),  # free text is not a word
        (
            ["orch", "ghp_x"],
            "orch",
        ),  # a lone word is a subcommand shape: no way to tell, but no value after it
    ):
        monkeypatch.setattr(sys, "argv", argv)
        addons.home()
        assert _trace_lines(h)[-1]["cmd"] == cmd
    raw = addons._trace_log_path().read_text(encoding="utf-8")
    assert "orn_secret123" not in raw and "Müller" not in raw and "--token" not in raw


def test_fallback_trace_untrusted_gets_its_reason_and_strict_writes_nothing(proj, monkeypatch):
    h = addons.real_home()
    _trace_on(monkeypatch)
    monkeypatch.delenv("ORCH_HOME_STRICT")
    monkeypatch.setenv("ORCH_HOME", str(proj / "inside"))
    addons.home()
    monkeypatch.setenv("ORCH_HOME", str(h.parent / "elsewhere"))
    addons.home()
    assert [x["reason"] for x in _trace_lines(h)] == ["untrusted:cwd", "untrusted:outside-home"]
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    with pytest.raises(Refused):
        addons.home()
    assert len(_trace_lines(h)) == 2
    monkeypatch.setenv("ORCH_HOME", str(h / "ok"))  # trusted: no line either
    addons.home()
    assert len(_trace_lines(h)) == 2


def test_fallback_trace_is_bounded_over_256kb_without_rotating(proj, monkeypatch):
    h = addons.real_home()
    _trace_on(monkeypatch)
    monkeypatch.delenv("ORCH_HOME")
    monkeypatch.delenv("ORCH_HOME_STRICT")
    log = addons._trace_log_path()
    log.write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    addons.home()
    assert log.stat().st_size < 1000 and len(_trace_lines(h)) == 1
    assert not list(log.parent.glob(f"{log.name}.*"))  # no second generation anywhere
    assert not (h / ".orch-tool").exists()


def test_fallback_trace_does_not_follow_a_symlink_and_fixes_the_mode(proj, monkeypatch):
    h = addons.real_home()
    _trace_on(monkeypatch)
    monkeypatch.delenv("ORCH_HOME")
    monkeypatch.delenv("ORCH_HOME_STRICT")
    d = h / ".orch-tool"
    log = addons._trace_log_path()
    target = h / "victim.txt"
    target.write_text("keep", encoding="utf-8")
    log.symlink_to(target)
    assert addons.home() == d  # still works
    assert target.read_text(encoding="utf-8") == "keep"
    log.unlink()
    log.write_text("", encoding="utf-8")
    log.chmod(0o666)
    addons.home()
    assert log.stat().st_mode & 0o777 == 0o600
    # a symlinked tool folder is never written to
    other = h / "other"
    other.mkdir()
    d2 = h / "x2"
    d2.mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: d2)
    (d2 / ".orch-tool").symlink_to(other)
    addons.home()
    assert list(other.iterdir()) == []


def test_strict_refuses_unset_empty_real_and_bare_home(proj, monkeypatch):
    h = addons.real_home()
    for strict in ("1", "true", "yes"):  # anything but empty or 0 is on
        monkeypatch.setenv("ORCH_HOME_STRICT", strict)
        monkeypatch.delenv("ORCH_HOME", raising=False)
        with pytest.raises(Refused, match="not set"):
            addons.home()
        for v, msg in (
            ("", "not set"),
            (str(h / ".orch-tool"), "real"),
            (str(h / "x" / ".." / ".orch-tool"), "real"),
            (str(h), "not a trusted"),
            (str(h).upper(), "not a trusted|real"),  # case-insensitive volumes
        ):
            monkeypatch.setenv("ORCH_HOME", v)
            with pytest.raises(Refused, match=msg):
                addons.home()
    for off in ("0", ""):
        monkeypatch.setenv("ORCH_HOME_STRICT", off)
        monkeypatch.delenv("ORCH_HOME", raising=False)
        assert addons.home() == h / ".orch-tool"  # non-strict: unchanged


def test_strict_cwd_check_ignores_case(proj, monkeypatch):
    h = addons.real_home()
    (h / "Work").mkdir()
    monkeypatch.chdir(h / "Work")
    monkeypatch.setenv("ORCH_HOME", str(h / "WORK" / "tool"))
    with pytest.raises(Refused):
        addons.home()


def test_strict_trusted_orch_home_works(proj, monkeypatch):
    ok = addons.real_home() / "cfg" / "orchhome"
    monkeypatch.setenv("ORCH_HOME", str(ok))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
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
    assert run("addon", "add", "hello")[0] == 2  # the fake install exposes no package
    assert uv_calls and uv_calls[0][-1].endswith("#subdirectory=workspace-addons/hello")
    assert not addons.registry_path().exists()
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
    monkeypatch.setattr(addons, "_same_python", lambda: [])  # the Windows pin has its own test
    addons._save_registry([{"name": "dashboard", "source": "built-in", "version": "0.0.0"}])
    addons._install_tool(addons.registry() + [{"name": "focus", "source": "built-in", "version": "0.0.0"}])
    args = uv_calls[0]
    assert all(isinstance(a, str) for a in args)
    zip_ = "https://github.com/someone/orch/archive/develop.zip"
    assert args[:5] == ["tool", "install", "--reinstall", "--refresh", f"{zip_}#subdirectory=workspace"]
    assert args[5:] == [
        "--with",
        f"{zip_}#subdirectory=workspace-addons/dashboard",
        "--with",
        f"{zip_}#subdirectory=workspace-addons/focus",
    ]
    monkeypatch.setenv("ORCH_REF", "v1")  # an explicit override still wins
    assert addons.spec("workspace").endswith("/archive/v1.zip#subdirectory=workspace")


def test_reinstall_keeps_its_python_on_every_platform(monkeypatch, tmp_path):
    """uv must not pick a newer Python for an add-on add/remove or update (lib/python3.11 -> 3.13 broke the
    running services): the interpreter orch runs on, or at least its version."""
    exe = tmp_path / "cpython-3.11" / "bin" / "python3.11"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    for platform in ("win32", "darwin", "linux"):
        monkeypatch.setattr(addons.sys, "platform", platform)
        monkeypatch.setattr(addons.sys, "_base_executable", str(exe))
        assert addons._same_python() == ["--python", str(exe)]
    monkeypatch.setattr(addons.sys, "_base_executable", str(tmp_path / "gone"))
    v = addons.sys.version_info
    assert addons._same_python() == ["--python", f"{v.major}.{v.minor}"]


def test_github_sources_install_without_git(monkeypatch):
    """Windows PCs (and minimal Linux) often have no git, and users may not be allowed to install it:
    GitHub sources come as a zip download. Other hosts keep git."""
    monkeypatch.delenv("ORCH_REPO", raising=False)
    for repo, ref, want in [
        (
            "https://github.com/a/orch",
            "main",
            "https://github.com/a/orch/archive/main.zip#subdirectory=workspace",
        ),
        (
            "https://github.com/a/orch.git",
            "fix/win",
            "https://github.com/a/orch/archive/fix/win.zip#subdirectory=workspace",
        ),
        ("https://gitlab.com/a/orch", "main", "git+https://gitlab.com/a/orch@main#subdirectory=workspace"),
    ]:
        monkeypatch.setattr(addons, "_install_origin", lambda r=repo, f=ref: {"repo": r, "ref": f})
        monkeypatch.delenv("ORCH_REF", raising=False)
        assert addons.spec("workspace") == want


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
        (
            {
                "url": "https://github.com/a/orch/archive/develop.zip",
                "archive_info": {},
                "subdirectory": "workspace",
            },
            {"repo": "https://github.com/a/orch", "ref": "develop"},
        ),
        (
            {
                "url": "https://github.com/a/orch/archive/refs/heads/fix/win.zip",
                "archive_info": {},
                "subdirectory": "workspace",
            },
            {"repo": "https://github.com/a/orch", "ref": "fix/win"},
        ),
        (
            {
                "url": "https://github.com/a/orch/archive/refs/tags/v1.2.zip",
                "archive_info": {},
                "subdirectory": "workspace",
            },
            {"repo": "https://github.com/a/orch", "ref": "v1.2"},
        ),
        ({"url": "https://github.com/a/orch/archive/main.zip", "archive_info": {}, "subdirectory": "x"}, {}),
    ]
    for data, want in cases:
        monkeypatch.setattr(md, "distribution", lambda _n, d=data: D(d))
        assert addons._install_origin() == want


# ---- publish and relay are built-in add-ons -----------------------------------------------------------


def help_text(capfd, *flags) -> str:
    with pytest.raises(SystemExit):
        cli.main(list(flags or ["--help"]))
    return capfd.readouterr().out


def test_clean_init_shows_no_addon_commands(proj, run, capfd):
    assert run("init")[0] == 0
    for flag in ("--help", "--help-all"):
        out = help_text(capfd, flag)
        for name in ("publish", "relay", "dashboard", "automation"):
            assert f"    {name} " not in out and f"  {name}  " not in out, (flag, name, out)
    tree = (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8") + "".join(
        p.name for p in (proj / ".agents" / "skills").iterdir()
    )
    for name in ("publish", "relay", "dashboard", "automation"):
        assert f"orch-{name}" not in tree and f"orch {name}" not in tree
    rows = {r["name"]: r["active"] for r in json.loads(run("addon", "list", "--json")[1])}
    assert rows == {"publish": False, "relay": False}
    code, _, err = run("relay", "inbox")
    assert code == 2 and "Turn it on: orch addon add relay" in err
    code, _, err = run("publish", "whoami")
    assert code == 2 and "Turn it on: orch addon add publish" in err
    code, _, err = run("publish", "--help")
    assert code == 2 and "Turn it on: orch addon add publish" in err
    t = json.loads(run("ticket", "new", "T", "--json")[1])["id"]
    code, _, err = run("ask", t, "Ok?", "--phone")
    assert code == 2 and "orch addon add relay" in err
    assert json.loads(run("ticket", "show", t, "--json")[1])["questions"] == []  # nothing asked


def test_add_relay_and_publish_like_any_addon(proj, run, uv_calls, capfd):
    run("init")
    code, out, err = run("addon", "add", "relay")  # no tty, no --yes
    assert code == 2 and "Adds the command: orch relay" in err and "--yes" in err
    code, out, err = run("addon", "add", "relay", "--yes")
    assert code == 0 and "relay is turned on" in out and not uv_calls  # part of orch: nothing installed
    assert (proj / ".agents/skills/orch-relay/SKILL.md").is_file()
    assert "orch-relay" in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    out = help_text(capfd)
    assert "relay" in out.split("Add-ons:")[1] and "publish" not in out
    code, _, err = run("relay", "inbox")
    assert code == 2 and "not connected" in err  # on, but not connected yet
    code, _, err = run("addon", "uninstall", "relay")
    assert code == 2 and "part of orch" in err
    assert run("addon", "remove", "relay")[0] == 0
    assert not (proj / ".agents/skills/orch-relay").exists()
    assert not (proj / ".orch/harness/AGENTS.orch.md").exists() or "orch-relay" not in (
        proj / ".orch/harness/AGENTS.orch.md"
    ).read_text(encoding="utf-8")
    assert run("relay", "inbox")[0] == 2


def test_core_addon_names_stay_reserved_for_others(tmp_path, run, proj, uv_calls):
    folder = make_addon(tmp_path / "x", mutate=lambda t: t.replace('name = "hello"', 'name = "relay"'))
    with pytest.raises(Refused, match="core command"):
        addons.folder_manifest(folder)


@pytest.mark.parametrize(
    "bad",
    ["../../evil/x/archive/main", "main#subdirectory=x", "a b", "-x", 'm"--index-url', "/abs", "x.lock"],
)
def test_install_ref_is_a_plain_ref_name(monkeypatch, bad):
    """In a zip URL a '../' would reach another repository (security review of the zip installs)."""
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.setattr(addons, "_install_origin", lambda: {})
    monkeypatch.setenv("ORCH_REF", bad)
    with pytest.raises(Refused):
        addons.spec("workspace")


@pytest.mark.parametrize(
    "good", ["main", "fix/windows-install", "v1.2.3", "ae5bb70c633d4a543d73a247d68449fac9d98150"]
)
def test_install_ref_accepts_branches_tags_commits(monkeypatch, good):
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.setattr(addons, "_install_origin", lambda: {})
    monkeypatch.setenv("ORCH_REF", good)
    assert addons.spec("workspace").endswith(f"/archive/{good}.zip#subdirectory=workspace")


def test_install_repo_with_quotes_or_spaces_is_refused(monkeypatch):
    monkeypatch.setattr(addons, "_install_origin", lambda: {})
    monkeypatch.delenv("ORCH_REF", raising=False)
    monkeypatch.setenv("ORCH_REPO", 'https://github.com/a/orch" --index-url x')
    with pytest.raises(Refused):
        addons.spec("workspace")


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["install", "manifest", "unshipped"])
def test_failed_add_preserves_registry(proj, tmp_path, monkeypatch, run, uv_calls, existing, failure):
    path = addons.registry_path()
    before = b'[  {"name": "automation", "source": "built-in", "version": "0.2.0"} ]\n'
    if existing:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(before)
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    monkeypatch.setattr(addons, "repo", lambda: "https://github.com/example/orch")
    source = "not-shipped"
    if failure != "unshipped":
        source = str(make_addon(tmp_path / "addon"))
    if failure == "install":

        def fail(args):
            raise Refused("install failed")

        monkeypatch.setattr(addons, "run_uv", fail)
    assert run("addon", "add", source, "--yes")[0] == 2
    assert path.read_bytes() == before if existing else not path.exists()
    code, _, err = run("addon", "list")
    assert code == 0
    assert "add-on list entry" not in err


@pytest.mark.parametrize("kind", ["normal", "test"])
def test_sync_is_shipped_and_can_be_added(proj, monkeypatch, run, uv_calls, kind):
    import tomllib

    import jsonschema

    from orch import humanproof

    base = Path(__file__).resolve().parents[2]
    folder = base / "workspace-addons" / "sync"
    manifest = folder / "src" / "orch_sync" / addons.MANIFEST
    jsonschema.validate(
        tomllib.loads(manifest.read_text()),
        json.loads((base / "contracts" / "addon-manifest.schema.json").read_text()),
    )
    assert "sync" in addons.SHIPPED_ADDONS
    assert addons.folder_manifest(folder)["recommended"] is False
    # proj fakes real_home: exercise the default home without touching the account home.
    monkeypatch.delenv("ORCH_HOME_STRICT")
    monkeypatch.setenv("ORCH_HOME", str(addons.real_home() / ".orch-tool"))
    monkeypatch.setattr(humanproof, "install_kind", lambda: kind)
    monkeypatch.setattr(addons, "repo", lambda: "https://github.com/example/orch")
    monkeypatch.setattr(addons, "_entry_points", lambda: {"sync": "orch_sync"} if uv_calls else {})
    monkeypatch.setattr(addons, "_manifest_file", lambda module: manifest)
    code, _, err = run("addon", "add", "sync", "--yes")
    assert code == 0, err
    assert "sync" in addons.active(proj)
    assert "--with" in uv_calls[0]
    assert any("workspace-addons/sync" in arg for arg in uv_calls[0])
    assert "add-on list entry" not in run("addon", "list")[2]


@pytest.mark.parametrize("value", ["true", "false", None])
def test_ticket_ext_inert_manifest_boolean(tmp_path, value):
    extra = f"ticket_ext_inert = {value}" if value is not None else ""
    folder = make_addon(tmp_path / "a", extra=extra)
    assert addons.folder_manifest(folder)["ticket_ext_inert"] is (value == "true")


def test_ticket_ext_inert_manifest_refuses_truthy_string(tmp_path):
    folder = make_addon(tmp_path / "a", extra='ticket_ext_inert = "true"')
    with pytest.raises(Refused, match="ticket_ext_inert"):
        addons.folder_manifest(folder)


def test_failed_batch_puts_the_list_and_the_tool_env_back(proj, monkeypatch, uv_calls):
    """#437: a POSIX batch whose project step fails leaves neither the add-on list nor orch's tool env with
    the add-ons it collected."""
    from orch import winfinish

    monkeypatch.setattr(winfinish, "needed", lambda: False)
    path = addons.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    before = b'[{"name": "automation", "source": "built-in", "version": "1"}]'
    path.write_bytes(before)

    def reexec(args):
        raise Refused("The project step failed (see above).")

    monkeypatch.setattr(addons, "reexec", reexec)
    with pytest.raises(Refused, match="project step failed"), addons.batch_install(proj):
        for n in ("dashboard", "focus"):
            entry = {"name": n, "source": "built-in", "version": "1"}
            addons._batch_for(proj).items.append((entry, [["addon", "add", n, "--project-only"]]))
    assert path.read_bytes() == before
    assert len(uv_calls) == 2  # the batch's install, then the one that puts the previous add-ons back
    assert uv_calls[0].count("--with") == 3
    assert uv_calls[1].count("--with") == 1 and any("workspace-addons/automation" in a for a in uv_calls[1])
    assert not addons.consented(proj, "dashboard") and not addons.consented(proj, "focus")


def test_insights_is_shipped_and_its_manifest_is_valid():
    import tomllib

    import jsonschema

    base = Path(__file__).resolve().parents[2]
    folder = base / "workspace-addons" / "insights"
    manifest = folder / "src" / "orch_insights" / addons.MANIFEST
    jsonschema.validate(
        tomllib.loads(manifest.read_text()),
        json.loads((base / "contracts" / "addon-manifest.schema.json").read_text()),
    )
    assert "insights" in addons.SHIPPED_ADDONS and addons._builtin_ok("insights")
    m = addons.folder_manifest(folder)
    assert m["name"] == "insights" and m["recommended"] is False  # one click to add, never on by default
    assert m["dashboard"]["label"] == "Insights" and m["page"]["path"] == "/"


def test_insights_can_be_added_and_removed(proj, monkeypatch, run, uv_calls):
    base = Path(__file__).resolve().parents[2]
    manifest = base / "workspace-addons" / "insights" / "src" / "orch_insights" / addons.MANIFEST
    monkeypatch.delenv("ORCH_HOME_STRICT")
    monkeypatch.setenv("ORCH_HOME", str(addons.real_home() / ".orch-tool"))
    monkeypatch.setattr(addons, "repo", lambda: "https://github.com/example/orch")
    monkeypatch.setattr(addons, "_entry_points", lambda: {"insights": "orch_insights"} if uv_calls else {})
    monkeypatch.setattr(addons, "_manifest_file", lambda module: manifest)
    code, _, err = run("addon", "add", "insights", "--yes")
    assert code == 0, err
    assert "insights" in addons.active(proj)
    assert any("workspace-addons/insights" in arg for arg in uv_calls[0])
    code, out, err = run("addon", "list")
    assert code == 0 and "insights" in out, err
    code, _, err = run("addon", "remove", "insights")
    assert code == 0, err
    assert "insights" not in addons.active(proj)


def test_factory_is_shipped_and_its_manifest_is_valid():
    import tomllib

    import jsonschema

    base = Path(__file__).resolve().parents[2]
    folder = base / "workspace-addons" / "factory"
    manifest = folder / "src" / "orch_factory" / addons.MANIFEST
    jsonschema.validate(
        tomllib.loads(manifest.read_text()),
        json.loads((base / "contracts" / "addon-manifest.schema.json").read_text()),
    )
    assert "factory" in addons.SHIPPED_ADDONS and addons._builtin_ok("factory")
    m = addons.folder_manifest(folder)
    assert m["name"] == "factory"
    assert m["requires"] == []  # its own watcher wakes the agent
    assert m["dashboard"]["label"] == "Factory"
    assert m["needs"] is True


def test_list_shows_shipped_addons_not_installed_yet(proj, run, tmp_path, monkeypatch):
    """The catalogue lists a shipped add-on that is not installed (installed false, never active), read
    from the local source folder with no network; installed ones keep installed true."""
    repo = tmp_path / "repo"
    make_addon(repo / "workspace-addons", name="factory")
    monkeypatch.setenv("ORCH_REPO", str(repo))
    monkeypatch.setattr(addons, "_entry_points", lambda: {})

    def no_network(name):
        raise AssertionError("addon list must not fetch")

    monkeypatch.setattr(addons, "preview_builtin", no_network)
    code, out, _ = run("addon", "list", "--json")
    rows = {r["name"]: r for r in json.loads(out)}
    assert code == 0
    assert rows["factory"]["installed"] is False and rows["factory"]["active"] is False
    assert rows["factory"]["running"] is False and rows["factory"]["source"] == "built-in"
    assert rows["factory"]["description"] == "Says hello."
    assert all(r["installed"] is True for n, r in rows.items() if n in addons.CORE_ADDONS)
    text = run("addon", "list")[1]
    assert "Available" in text and "factory" in text.split("Available", 1)[1]
    assert "factory" not in text.split("Available", 1)[0]
    # an installed shipped add-on is not listed twice and is installed true
    monkeypatch.setattr(addons, "_entry_points", lambda: {"factory": "orch_factory"})
    addons._save_registry([{"name": "factory", "source": "built-in", "version": "0.1.0"}])
    sys.path.insert(0, str(repo / "workspace-addons" / "factory" / "src"))
    try:
        rows = [r for r in json.loads(run("addon", "list", "--json")[1]) if r["name"] == "factory"]
    finally:
        sys.path.remove(str(repo / "workspace-addons" / "factory" / "src"))
    assert len(rows) == 1 and rows[0]["installed"] is True


def _not_local(monkeypatch):
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.setattr(addons, "_install_origin", lambda: {})
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    monkeypatch.setattr(addons, "preview_builtin", lambda n: pytest.fail("no network in list"))


@pytest.mark.real_bundle
def test_list_uses_the_bundle_on_a_normal_install(proj, run, monkeypatch):
    """No source folder: the shipped add-ons that are not installed come from shipped_addons.json."""
    _not_local(monkeypatch)
    assert not addons._is_local(addons.repo())
    rows = {r["name"]: r for r in json.loads(run("addon", "list", "--json")[1])}
    for n in addons.SHIPPED_ADDONS:
        assert rows[n]["installed"] is False and rows[n]["active"] is False and rows[n]["running"] is False
        assert rows[n]["source"] == "built-in" and rows[n]["description"]


@pytest.mark.real_bundle
def test_list_leaves_out_an_addon_that_is_in_neither_source(proj, run, monkeypatch):
    _not_local(monkeypatch)
    real = addons.bundled_manifests()
    monkeypatch.setattr(
        addons, "bundled_manifests", lambda: {n: m for n, m in real.items() if n != "factory"}
    )
    names = [r["name"] for r in json.loads(run("addon", "list", "--json")[1])]
    assert "factory" not in names and "focus" in names


def test_bundle_matches_the_manifests(tmp_path):
    """shipped_addons.json is generated: a manifest change without regenerating fails here."""
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "scripts" / "gen_shipped_addons.py"
    spec = importlib.util.spec_from_file_location("gen_shipped_addons", script)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.OUT.read_text(encoding="utf-8") == gen.render(), (
        "workspace/src/orch/shipped_addons.json is out of date: run python3 scripts/gen_shipped_addons.py"
    )
