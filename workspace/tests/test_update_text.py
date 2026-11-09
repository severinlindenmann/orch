"""Update text across the install/reexec boundary, without installing or starting anything."""

import json

import pytest
from test_addons import run, uv_calls  # noqa: F401
from test_addons_upgrade import _write_registry, github  # noqa: F401

from orch import addons, services


@pytest.fixture
def source(proj, github, uv_calls, monkeypatch):  # noqa: F811
    state = {"orch": "0.9.3", "addon": "0.3.1", "sha": "aaaaaaaa1234", "title": None}
    _write_registry([{"name": "dashboard", "source": "built-in", "version": "0.3.1"}])
    (addons.home() / "installed.json").write_text(json.dumps({"sha": state["sha"]}))
    monkeypatch.setattr(
        addons, "_install_origin", lambda: {"repo": "https://github.com/o/orch", "ref": "main"}
    )
    monkeypatch.setattr(addons, "_orch_version", lambda: state["orch"])
    monkeypatch.setattr(addons, "_source_sha", lambda: state["sha"])
    monkeypatch.setattr(addons, "_release_title", lambda: state["title"])
    monkeypatch.setattr(addons, "discover", lambda: {"dashboard": {"version": state["addon"]}})
    monkeypatch.setattr(services, "running", lambda: [])

    def install(args):
        uv_calls.append(args)
        snapshot = json.loads((addons.home() / "update-before.json").read_text())
        assert snapshot == {"orch": "0.9.3", "addons": {"dashboard": "0.3.1"}, "sha": state["sha"]}
        state.update(state.get("next", {}))

    monkeypatch.setattr(addons, "run_uv", install)
    state["next"] = {"orch": "0.9.4", "addon": "0.3.2", "sha": "bbbbbbbb5678"}
    return state


def test_versions_and_sha(proj, run, source):  # noqa: F811
    code, out, err = run("update")
    assert code == 0, err
    assert out.splitlines() == [
        "Updating orch 0.9.3 → 0.9.4 (main aaaaaaaa → bbbbbbbb)",
        "Updating dashboard 0.3.1 → 0.3.2",
    ]
    assert not (addons.home() / "update-before.json").exists()
    assert json.loads((addons.home() / "installed.json").read_text()) == {"sha": "bbbbbbbb5678"}


def test_release_title(proj, run, source):  # noqa: F811
    source["title"] = "Fixes the sign button"
    code, out, err = run("update")
    assert code == 0, err
    assert out.splitlines()[-1] == "Fixes the sign button"
    assert out.count("Fixes the sign button") == 1


def test_unchanged_does_not_restart(proj, run, source, monkeypatch):  # noqa: F811
    source["next"] = {}
    monkeypatch.setattr(services, "running", lambda: pytest.fail("must not inspect/restart services"))
    code, out, err = run("update")
    assert code == 0, err
    assert out == "orch is up to date.\n"


@pytest.mark.parametrize("failure", [None, "row", "stop", "start"])
def test_restart_only_running_here(proj, run, source, monkeypatch, failure):  # noqa: F811
    monkeypatch.setattr(
        services,
        "running",
        lambda: [
            {"workspace": str(proj.resolve()), "addon": "dashboard"},
            {"workspace": str(proj.resolve()), "addon": "focus"},
            {"workspace": str(proj / "elsewhere"), "addon": "automation"},
        ],
    )
    calls = []

    def stop(root, only=None):
        calls.append(("stop", root, only))
        if failure == "stop":
            raise RuntimeError("stop failed")

    def start(root, only=None):
        calls.append(("start", root, only))
        if failure == "start":
            raise RuntimeError("start failed")
        return [{"addon": "dashboard", "running": True}, {"addon": "focus", "running": failure != "row"}]

    monkeypatch.setattr(services, "stop", stop)
    monkeypatch.setattr(services, "start", start)
    code, out, err = run("update")
    assert code == 0, err
    assert calls == [
        (c, proj, {"dashboard", "focus"}) for c in (["stop"] if failure == "stop" else ["stop", "start"])
    ]
    if failure:
        assert "Restart focus to use the new version\n" in out
    if failure == "row":
        assert "Restarting dashboard… done\n" in out
    elif failure is None:
        assert "Restarting dashboard, focus… done\n" in out
    else:
        assert "Restart dashboard to use the new version\n" in out
        assert "… done" not in out


def test_plain_project_only(proj, run, source):  # noqa: F811
    code, out, err = run("update", "--project-only")
    assert code == 0, err
    assert out == "Refreshed: nothing\n"


@pytest.mark.parametrize("args", [(), ("--project-only",)])
def test_json(proj, run, source, args):  # noqa: F811
    code, out, err = run("update", *args, "--json")
    assert code == 0, err
    assert json.loads(out) == {"ok": True, "refreshed": []}


def test_sha_only(proj, run, source):  # noqa: F811
    source["next"] = {"sha": "bbbbbbbb5678"}
    code, out, err = run("update")
    assert code == 0, err
    assert out == "Updating orch 0.9.3 (main aaaaaaaa → bbbbbbbb)\n"


def test_service_filter_preserves_other_records(proj, monkeypatch):
    (proj / ".orch").mkdir()
    entries = [{"workspace": str(proj.resolve()), "addon": n, "pid": 123} for n in ("dashboard", "focus")]
    monkeypatch.setattr(services, "running", lambda: entries)
    monkeypatch.setattr(
        services, "_services", lambda root: {n: {} for n in ("dashboard", "focus", "automation")}
    )
    monkeypatch.setattr(services, "workspace_rows", lambda root: [])
    calls, saved = [], []
    monkeypatch.setattr(services, "_save", lambda rows: saved.append(rows))
    monkeypatch.setattr(services, "_call", lambda root, name, m, sub: calls.append((name, sub)) or {})
    services.stop(proj, only={"dashboard"})
    services.start(proj, only={"dashboard"})
    assert calls == [("dashboard", "stop"), ("dashboard", "start")]
    assert saved == [[entries[1]], [entries[1]]]


@pytest.mark.parametrize(
    "old_sha,new_sha,suffix",
    [
        (None, "bbbbbbbb5678", " (main → bbbbbbbb)"),
        ("aaaaaaaa1234", None, ""),
    ],
)
def test_missing_sha(proj, run, source, old_sha, new_sha, suffix):  # noqa: F811
    source["sha"] = old_sha
    source["next"]["sha"] = new_sha
    (addons.home() / "installed.json").write_text(json.dumps({"sha": old_sha}))
    code, out, err = run("update")
    assert code == 0, err
    assert out.splitlines()[0] == "Updating orch 0.9.3 → 0.9.4" + suffix


@pytest.mark.parametrize(
    "release,expected",
    [
        ({"name": "Fixes the sign button\nMore details"}, "Fixes the sign button"),
        ({"name": "", "body": "First line\nSecond line"}, "First line"),
        ({"name": "x" * 120 + "\x00"}, "x" * 100),
        ({}, None),
    ],
)
def test_release_metadata(github, monkeypatch, release, expected):  # noqa: F811
    import io
    import urllib.request

    calls = []

    def urlopen(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(json.dumps(release).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert addons._release_title() == expected
    assert calls == [("https://api.github.com/repos/o/orch/releases/latest", 5)]
