"""v2 manifest keys: recommended, gitignore, runs_agents, requires, needs, [page], open-page rows."""

import json

import pytest
from test_addons import hello, install, make_addon, run, third_party, uv_calls  # noqa: F401

from orch import addons
from orch.errors import Refused


def _gi(proj):
    f = proj / ".gitignore"
    return f.read_text(encoding="utf-8") if f.exists() else ""


@pytest.mark.parametrize(
    "extra",
    [
        'gitignore = ["../x"]',
        'gitignore = ["/abs"]',
        'gitignore = ["a\\\\b"]',
        'gitignore = ["C:x"]',
        'gitignore = "x"',
        'recommended = "yes"',
        "needs = 1",
        'requires = ["Bad Name"]',
        'requires = ["a", "a"]',
        "[page]\npath = '/x'",  # page without background
    ],
)
def test_bad_values_refused(tmp_path, extra):
    folder = make_addon(tmp_path, extra=extra)
    with pytest.raises(Refused):
        addons.folder_manifest(folder)


def test_page_needs_background_and_valid_path(tmp_path):
    ok = make_addon(tmp_path / "a", bg=True, extra='[page]\npath = "/notes"\nlabel = "Open notes"\n')
    # the extra table must come before [dashboard]; make_addon puts it right after background
    assert addons.folder_manifest(ok)["page"] == {"path": "/notes", "label": "Open notes"}
    for bad in ('path = "/x\\n"', 'path = "notes"', 'path = "/a/../b"', 'path = "//x"'):
        f = make_addon(tmp_path / bad.replace('"', "").replace("/", "_"), bg=True, extra=f"[page]\n{bad}\n")
        with pytest.raises(Refused):
            addons.folder_manifest(f)


def test_open_page_row_needs_page(tmp_path):
    def row(t):
        return t.replace('format = "text"', 'format = "open-page"')

    with pytest.raises(Refused):
        addons.folder_manifest(make_addon(tmp_path / "a", mutate=row))
    ok = make_addon(tmp_path / "b", bg=True, extra='[page]\npath = "/n"\n', mutate=row)
    assert addons.folder_manifest(ok)["ticket_view"][0]["format"] == "open-page"


def test_new_keys_default_and_reserved_names(tmp_path):
    m = addons.folder_manifest(make_addon(tmp_path))
    assert (m["recommended"], m["runs_agents"], m["needs"], m["gitignore"], m["requires"]) == (
        False,
        False,
        False,
        [],
        [],
    )
    for n in ("run", "needs", "agents"):
        assert n in addons.RESERVED


def test_gitignore_added_on_add_removed_on_remove(proj, run, tmp_path, monkeypatch, uv_calls):  # noqa: F811
    import subprocess

    (proj / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    ex = proj / ".git/info/exclude"
    folder = make_addon(tmp_path / "s", extra='gitignore = ["notes/cache/", "*.tmp"]')
    eps = {}
    monkeypatch.setattr(addons, "_entry_points", lambda: dict(eps))
    import sys

    sys.path.insert(0, str(folder / "src"))
    monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
    eps["hello"] = "orch_hello"
    try:
        code, _, err = run("addon", "add", str(folder), "--yes")
        assert code == 0, err
        g = ex.read_text(encoding="utf-8")
        assert "# orch:begin addon-hello\n/notes/cache/\n/*.tmp\n# orch:end addon-hello" in g
        assert _gi(proj) == "node_modules/\n"  # the team's .gitignore is never edited
        run("addon", "add", str(folder), "--yes")  # again: no duplicate block
        assert ex.read_text(encoding="utf-8").count("notes/cache/") == 1
        code, _, err = run("addon", "remove", "hello")
        assert code == 0, err
        assert "addon-hello" not in ex.read_text(encoding="utf-8")
    finally:
        sys.path.remove(str(folder / "src"))


def test_requires_refuses_naming_the_missing_one(proj, run, tmp_path, uv_calls):  # noqa: F811
    folder = make_addon(tmp_path / "r", extra='requires = ["other"]')
    code, out, err = run("addon", "add", str(folder), "--yes")
    assert code == 2 and "other" in err and "orch addon add other" in err
    assert not (proj / ".orch" / "addons.json").exists()


def test_list_text_and_json_new_fields(proj, run, hello):  # noqa: F811
    install(run, hello)
    code, out, _ = run("addon", "list")
    line = next(x for x in out.splitlines() if "hello" in x)
    assert line == "  hello       on    Says hello."
    row = next(r for r in json.loads(run("addon", "list", "--json")[1]) if r["name"] == "hello")
    assert row["recommended"] is False and row["page"] is None and row["running"] is False


def test_exclude_block_is_idempotent_and_keeps_other_lines(proj):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    ex = proj / ".git/info/exclude"
    ex.write_text("mine/\n", encoding="utf-8")
    addons._set_gitignore(proj, "hello", ["x/"])
    addons._set_gitignore(proj, "hello", ["x/"])
    assert ex.read_text(encoding="utf-8") == "mine/\n# orch:begin addon-hello\n/x/\n# orch:end addon-hello\n"
    addons._set_gitignore(proj, "hello", [])
    assert ex.read_text(encoding="utf-8") == "mine/\n"


def test_shipped_local_addons_are_recommended_and_server_ones_are_not():
    """`orch init --recommended` only does something when manifests say so: dashboard, automation, focus."""
    import tomllib
    from pathlib import Path

    base = Path(__file__).resolve().parents[2] / "workspace-addons"
    got = {}
    for f in sorted(base.glob("*/src/*/orch-addon.toml")):
        m = tomllib.loads(f.read_text(encoding="utf-8"))
        got[m["name"]] = m.get("recommended", False)
    assert got["dashboard"] and got["automation"] and got["focus"], got
    assert not any(v for k, v in got.items() if k not in ("dashboard", "automation", "focus")), got
