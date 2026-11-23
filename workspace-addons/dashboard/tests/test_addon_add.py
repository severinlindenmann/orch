"""ORCH-1739: add several add-ons in one run from the dashboard. POST /api/act {op: addon.add, args: {names}} starts
the core's job (`orch.addonjob.launch`) and answers 202 with the job at once; GET /api/addon-job reads it. The core
module is faked here (it is built in workspace/src/orch/addonjob.py)."""

import http.client
import json
import os
import sys
import threading

import pytest

pytest.importorskip("orch")
import orch
from orch import addons, pagelaunch, pagesession

from orch_dashboard import actions, data, server
from orch_dashboard.server import make_server

ROWS = [
    {"name": "browse", "installed": False, "active": False, "dashboard": {"label": "Browser"}},
    {"name": "files", "installed": False, "active": False},
    {"name": "lessons", "installed": True, "active": False},
    {"name": "sync", "installed": True, "active": True, "dashboard": {"label": "Backup"}},
    {"name": "dashboard", "installed": True, "active": True},
]


@pytest.fixture
def job_mod(tmp_path, monkeypatch):
    """The real orch.addonjob with its job file in a test folder; the command it starts is recorded, never run."""
    from orch import addonjob

    monkeypatch.setattr(addonjob, "_home", lambda: tmp_path / "toolhome")
    monkeypatch.setattr(addonjob, "_update_running", lambda: False)
    addonjob.calls = []

    class Child:
        pid = os.getpid()  # alive: the job stays live while the test looks

    def popen(argv, **kw):
        addonjob.calls.append((argv, kw["cwd"], kw["env"].get(addonjob.ENV)))
        return Child()

    monkeypatch.setattr(addonjob, "_popen", popen)
    yield addonjob
    del addonjob.calls


@pytest.fixture
def listing(monkeypatch):
    monkeypatch.setattr(
        actions, "run_orch", lambda b, args, root: ROWS if args == ["addon", "list", "--json"] else None
    )
    monkeypatch.setattr(actions, "human_env", lambda root, orch_bin: {"ORCH_VIA": "dashboard"})


def test_names_are_checked_against_the_catalogue(tmp_path, job_mod, listing):
    for bad in (None, [], ["Browse"], ["browse", "browse"], ["dashboard"], "browse", [1], ["x" * 40]):
        with pytest.raises(actions.BadRequest, match="Pick the add-ons"):
            actions.addon_add(tmp_path, "orch", {"names": bad})
    with pytest.raises(actions.BadRequest, match="Not allowed here"):
        actions.addon_add(tmp_path, "orch", {"names": ["browse"], "yes": True})
    with pytest.raises(actions.BadRequest, match="not available here"):
        actions.addon_add(tmp_path, "orch", {"names": ["browse", "nothere"]})
    with pytest.raises(actions.BadRequest, match="Backup is already on"):
        actions.addon_add(tmp_path, "orch", {"names": ["browse", "sync"]})
    assert job_mod.calls == []  # nothing started for a refused pick


def test_one_launch_for_all_picks_and_the_job_without_paths(tmp_path, job_mod, listing):
    (tmp_path / ".orch").mkdir()
    code, text, job = actions.addon_add(tmp_path, "orch", {"names": ["browse", "files", "lessons"]})
    assert code == 202 and text == ""
    assert len(job_mod.calls) == 1
    argv, cwd, job_id = job_mod.calls[0]
    assert argv[-5:] == ["browse", "files", "lessons", "--yes", "--job"] and cwd == str(tmp_path.resolve())
    assert job_id == job["id"]
    assert job["state"] == "running" and job["here"] is True
    assert [s["key"] for s in job["steps"]] == ["ready", "on:browse", "on:files", "on:lessons", "restart"]
    assert "workspace" not in job and "pid" not in job  # never the folder or a process id
    log = (tmp_path / ".orch" / "run" / "dashboard" / "actions.log").read_text(encoding="utf-8")
    assert '"op": "addon.add"' in log and "browse,files,lessons" in log


def test_a_live_job_is_refused_with_the_cores_sentence(tmp_path, job_mod, listing):
    assert actions.addon_add(tmp_path, "orch", {"names": ["browse"]})[0] == 202
    code, text, job = actions.addon_add(tmp_path, "orch", {"names": ["files"]})
    assert (code, job) == (409, None)
    assert text == job_mod.BUSY == "orch is already adding add-ons. You can add more when this is done."
    assert len(job_mod.calls) == 1


def test_an_older_core_without_jobs_says_so(tmp_path, listing, monkeypatch):
    monkeypatch.setitem(sys.modules, "orch.addonjob", None)  # import fails
    monkeypatch.delattr(orch, "addonjob", raising=False)
    with pytest.raises(actions.Unavailable, match="newer orch"):
        actions.addon_add(tmp_path, "orch", {"names": ["browse"]})
    assert actions.addon_job(tmp_path) is None


def test_the_job_read_keeps_only_what_the_page_needs(tmp_path, job_mod, listing, monkeypatch):
    assert actions.addon_job(tmp_path) is None
    actions.addon_add(tmp_path, "orch", {"names": ["browse"]})
    got = actions.addon_job(tmp_path)
    assert got["names"] == ["browse"] and got["here"] is True
    assert set(got) <= set(actions._JOB_KEYS)
    assert actions.addon_job(tmp_path / "elsewhere")["here"] is False  # another workspace's run

    def broken(root=None):
        raise ValueError("bad file")

    monkeypatch.setattr(job_mod, "read", broken)
    assert actions.addon_job(tmp_path) is None  # an unreadable job file is no job, never an error page


def test_the_catalogue_passes_requires_through_when_the_listing_has_it(tmp_path, monkeypatch):
    rows = [
        {"name": "publish", "installed": False, "active": False, "requires": ["relay", "BAD NAME"]},
        {"name": "relay", "installed": True, "active": False},
    ]
    monkeypatch.setattr(
        data, "run_orch", lambda b, args, root: rows if args == ["addon", "list", "--json"] else None
    )
    ws = tmp_path / "ws"
    (ws / ".orch").mkdir(parents=True)
    out = data.load_settings(ws, "orch")
    assert out["available"][0]["requires"] == ["relay"]
    assert "requires" not in out["addons"][0]


# --- through the real server, with a page session ---


@pytest.fixture
def live(tmp_path, monkeypatch, job_mod, listing):
    acct = tmp_path / "acct"
    (acct / ".orch-test").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    (acct / ".orch-test" / "home").mkdir()
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    import subprocess

    def no_child(argv, *a, **k):
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(actions, "_run", no_child)
    monkeypatch.setattr(data, "_run", no_child)
    armed = []
    monkeypatch.setattr(server, "_arm_resume", lambda r, s: armed.append(r))
    srv = make_server(root, 0, orch_bin=pagesession.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, srv.server_address[1], armed
    srv.shutdown()
    srv.server_close()


def _req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", **(headers or {})}
    if body is not None:
        h["Content-Type"] = "application/json"
    c.request(method, path, None if body is None else json.dumps(body), h)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def _session(root, port):
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, hdr, body = _req(port, "POST", "/session", {"token": tok})
    assert st == 200
    return {"Cookie": hdr["Set-Cookie"].split(";")[0], "X-Orch-Page": json.loads(body)["secret"]}


def test_the_page_starts_one_run_and_reads_it_back(live, job_mod):
    root, port, armed = live
    me = _session(root, port)
    st, hdr, body = _req(
        port,
        "POST",
        "/api/act",
        {"op": "addon.add", "args": {"names": ["browse", "files"]}},
        {**me, "X-Orch-Op": "addon.add"},
    )
    assert st == 202, body
    got = json.loads(body)["job"]
    assert got["names"] == ["browse", "files"] and "workspace" not in got
    assert hdr.get("X-Orch-Boot")
    assert armed == [root]  # the restarted server takes this tab's session over, like addon.set
    assert len(job_mod.calls) == 1
    st, hdr, body = _req(port, "GET", "/api/addon-job", headers=me)
    assert st == 200 and json.loads(body)["job"]["id"] == got["id"]
    assert hdr.get("X-Orch-Boot") and hdr.get("Cache-Control") == "no-store"


def test_without_a_page_session_nothing_starts(live, job_mod):
    _root, port, armed = live
    st, _, _ = _req(port, "POST", "/api/act", {"op": "addon.add", "args": {"names": ["browse"]}})
    assert st in (401, 403)
    assert job_mod.calls == [] and armed == []
    st, _, _ = _req(port, "GET", "/api/addon-job")
    assert st in (401, 403)  # the job is read only with the sign-in


def test_a_refusal_is_409_with_plain_words(live, job_mod):
    root, port, _ = live
    me = _session(root, port)
    st, _, _ = _req(port, "POST", "/api/act", {"op": "addon.add", "args": {"names": ["browse"]}}, me)
    assert st == 202
    st, _, body = _req(port, "POST", "/api/act", {"op": "addon.add", "args": {"names": ["files"]}}, me)
    assert st == 409 and body.decode() == job_mod.BUSY
    st, _, body = _req(port, "POST", "/api/act", {"op": "addon.add", "args": {"names": ["nothere"]}}, me)
    assert st == 400 and b"not available here" in body
