"""`orch sync act <verb> -- <target>`: what the dashboard's Sync card and Needs rows run (one generic add-on op)."""

import hashlib
import io
import json
import subprocess
from types import SimpleNamespace

import pytest
from orch import humanproof
from test_step import ART, TICKET, configure, run, save, success
from test_two_machines import both, edit, machines

from orch_sync import act, cli, needs, pause, repo, step

__all__ = ["machines"]
SECRET = b"orp_" + b"a" * 30


def sync(root, *args):
    return cli.main(["--dir", str(root), "act", *args, "--json"])


def answer(capsys):
    return json.loads(capsys.readouterr().out)


def proof(root, target, monkeypatch):
    key = humanproof.human_key(root)
    token = humanproof.mint(key, humanproof.new_payload("addon.act", target, "human:Pat"))
    monkeypatch.setattr("sys.stdin", io.StringIO(token + "\n"))


def bare(tmp_path):
    path = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    return path


def test_status_off_then_local(root, capsys):
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["mode"] == "off" and card["shown"] == "off" and card["not_synced"] == [] and card["public"] is None
    assert sync(root, "set", "local") == 0
    assert answer(capsys)["mode"] == "local"
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["mode"] == "local"
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["shown"] == "never"
    (root / ".orch/run/sync/state.json").write_text('{"last_error":"offline","last_ok":"2026-11-11T10:15:00Z"}')
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["shown"] == "offline"
    (root / ".orch/run/sync/state.json").write_text('{"last_ok":"2026-11-11T10:15:00Z"}')
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["shown"] == "synced"
    assert sync(root, "set", "off") == 0
    assert answer(capsys)["mode"] == "off"
    # the argv the dashboard's generic op builds: flags, then the target after `--`
    assert cli.main(["--dir", str(root), "act", "status", "--by", "human:pat", "--json", "--", "sync"]) == 0
    assert answer(capsys)["shown"] == "off"
    assert cli.main(["--dir", str(root), "act", "set", "--value=15", "--by", "human:pat", "--json", "--", "-x"]) == 2


def test_set_is_a_persons_click(root, monkeypatch, capsys):
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    assert sync(root, "set", "local") == 2
    assert "A person chooses where sync keeps a copy" in answer(capsys)["error"]
    assert not (root / ".orch/run/sync/settings.json").exists()


def test_check_uses_syncs_own_transport_rules(root, tmp_path, capsys, normal_install):
    for bad in ("file:///tmp/x", "/tmp/x", "http://example.org/x", "ext::sh -c x", "https://me:pw@example.org/x"):
        assert sync(root, "check", bad) == 0
        got = answer(capsys)
        assert got["ok"] is False and got["reason"], bad
    assert not (root / ".orch/.git").exists()  # a check never sets anything up


def test_check_reaches_a_test_remote_and_reports_a_missing_one(root, tmp_path, capsys):
    assert sync(root, "check", f"file://{bare(tmp_path)}") == 0
    assert answer(capsys) == {"ok": True}
    assert sync(root, "check", f"file://{tmp_path / 'nothing-here.git'}") == 0
    assert answer(capsys)["ok"] is False
    assert not (root / ".orch/.git").exists()


def test_interval_and_remote_need_the_preview(root, tmp_path, monkeypatch, capsys):
    remote = f"file://{bare(tmp_path)}"
    assert sync(root, "set", remote, "--value", "15") == 2
    assert "preview-only" in answer(capsys)["error"]
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    assert sync(root, "set", remote, "--value", "7") == 2
    assert answer(capsys)["error"] == "Sync can run every 5, 15 or 60 minutes"
    assert sync(root, "set", remote, "--value", "60") == 0
    got = answer(capsys)
    assert got["mode"] == "remote" and got["interval"] == 60
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["remote"] == remote


def test_public_address_waits_for_the_signed_choice(root, tmp_path, monkeypatch, capsys):
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "public")
    remote = f"file://{bare(tmp_path)}"
    assert sync(root, "set", "local") == 0
    capsys.readouterr()
    assert sync(root, "set", remote, "--value", "15") == 0
    got = answer(capsys)
    assert got["public"] == remote and got["mode"] == "local"
    assert got["text"] == "This sync address is public. Anyone can read your tickets."
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["public"] == remote
    assert sync(root, "now", "sync") == 0  # never syncs to it while the choice waits
    assert answer(capsys)["text"] == "Not synced: choose a location above first"
    target = "sync:use-public:" + hashlib.sha256(remote.encode()).hexdigest()
    assert sync(root, "use-public", "pending", "--proof-target") == 0
    assert answer(capsys) == {"target": target}
    assert sync(root, "use-public", "pending") == 2  # no proof: refused
    capsys.readouterr()
    proof(root, target, monkeypatch)
    assert sync(root, "use-public", "pending", "--proof-stdin") == 0
    assert answer(capsys)["mode"] == "remote"
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["public"] is None and card["mode"] == "remote"


def test_keep_on_this_computer_drops_the_public_address(root, tmp_path, monkeypatch, capsys):
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "public")
    assert sync(root, "set", f"file://{bare(tmp_path)}", "--value", "5") == 0
    assert sync(root, "set", "local") == 0
    capsys.readouterr()
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["public"] is None and card["mode"] == "local"


def test_sync_now_never_clears_a_pause(root, monkeypatch, capsys):
    configure(root)
    save(root)
    save(root, ART, SECRET)
    assert "secret" in run(root)["last_error"]
    monkeypatch.setattr(step, "run_once", lambda *a, **k: pytest.fail("Sync now ran while paused"))
    capsys.readouterr()
    assert sync(root, "now", "sync") == 0
    got = answer(capsys)
    assert got == {"still_paused": 1, "text": "Still paused: 1 thing needs you"}
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["shown"] == "paused" and card["paused_needs"] == 1


def test_leave_it_out_is_signed_bound_to_the_bytes_and_ends_the_pause(root, monkeypatch, capsys):
    configure(root)
    save(root)
    save(root, ART, SECRET)
    run(root)
    rows = needs.rows(root)
    assert [r["text"] for r in rows] == ["Not synced: a.txt may contain a password or access key."]
    labels = [(a["label"], a.get("verb"), a.get("sign", False)) for a in rows[0]["actions"]]
    assert labels == [("Leave it out", "leave-out", True), ("View file", None, False)]
    assert rows[0]["actions"][1]["view"] == {"ticket": "t_abc123", "name": "a.txt"}
    capsys.readouterr()
    assert sync(root, "leave-out", ART, "--proof-target") == 0
    target = answer(capsys)["target"]
    assert target == "sync:leave-out:" + hashlib.sha256(ART.encode() + b"\0" + SECRET).hexdigest()
    with pytest.raises(Exception, match="proof|person"):
        pause.leave_out(root, ART, SimpleNamespace(proof_stdin=False, by="agent:test"))
    proof(root, target, monkeypatch)
    assert sync(root, "leave-out", ART, "--proof-stdin") == 0
    assert answer(capsys)["paused"] is False
    state = run(root)
    assert state["last_error"] is None and not state.get("paused"), state
    assert ART not in repo.git(root, "ls-files").stdout.decode()
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["not_synced"] == [{"name": "a.txt", "why": "may contain a password or access key"}]
    # changed content asks again
    save(root, ART, SECRET + b" changed")
    assert "secret" in run(root)["last_error"]


def test_proof_target_of_keep_theirs_is_what_resolve_checks(machines, monkeypatch, capsys):
    a, b, _ = both(machines)
    edit(a, title="Theirs")
    edit(b, title="Mine")
    success(a)
    with monkeypatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)  # the two copies can't be combined
        assert run(b)["paused"]["files"] == [TICKET]
    rows = needs.rows(b)
    row = rows[0]
    assert row["text"] == "Sync paused: “Mine” changed here and on another computer."
    keep = {x["verb"]: x for x in row["actions"]}
    assert keep["keep-mine"]["review"]["here"] == "Title: Mine" and keep["keep-mine"]["review"]["there"] == "Title: Theirs"
    assert all(x["sign"] for x in row["actions"])
    assert act.proof_target(b, "keep-mine", TICKET) is None
    target = act.proof_target(b, "keep-theirs", TICKET)
    assert target.startswith("sync:keep-theirs:")
    proof(b, target, monkeypatch)
    assert cli.main(["--dir", str(b), "act", "keep-theirs", TICKET, "--proof-stdin", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["text"] == "Kept the other version."
    assert json.loads(repo.safe(b, TICKET).read_text())["title"] == "Theirs"


def test_rows_keep_the_needs_shape(root):
    schema = json.loads((__import__("pathlib").Path(__file__).resolve().parents[3] / "contracts/needs.schema.json").read_text())
    configure(root)
    save(root)
    save(root, ART, SECRET)
    run(root)
    from jsonschema import Draft202012Validator

    Draft202012Validator(schema).validate(needs.rows(root))
