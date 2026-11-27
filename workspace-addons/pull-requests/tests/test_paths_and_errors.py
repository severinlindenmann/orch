"""Error paths, empty states and Windows-style folders (spaces, umlauts) of the queue file, the CLI, the watcher,
the group copy and the read of the Pull requests page. No real gh call; git runs on local test repositories."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from test_queue import bare, url  # noqa: F401  (bare: a fixture)

from orch_pull_requests import cli, poll, prread, service, store
from orch_pull_requests.group import Git
from orch_pull_requests.store import Refused

REPO = "acme/app"
ODD = "Mein Ordner ä ö ü"  # a OneDrive-style folder name


@pytest.fixture
def origin(request):
    """test_queue's bare repository: pull requests 1 and 2 add b.txt and c.txt, 3 and 4 both change shared.txt."""
    return request.getfixturevalue("bare")


@pytest.fixture
def odd_ws(tmp_path, monkeypatch):
    root = tmp_path / ODD / "Kunden Projekt é"
    (root / ".orch" / "tickets").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


# -- the queue file --------------------------------------------------------------------------------------
def test_the_queue_works_in_a_folder_with_spaces_and_umlauts(odd_ws):
    row, new = store.add(odd_ws, url(1), None, "human:p", login="bot")
    assert new and store.read(odd_ws) == [row]
    assert (odd_ws / ".orch" / "addons" / "pull-requests" / "queue.json").is_file()


def test_a_damaged_queue_file_is_empty_to_read_and_refused_to_change(ws):
    f = store.folder(ws) / "queue.json"
    f.parent.mkdir(parents=True)
    f.write_text("{not json", encoding="utf-8")
    assert store.read(ws) == []
    with pytest.raises(Refused, match="damaged.*Move it away"):
        store.add(ws, url(1), None, "human:p", login="bot")
    assert f.read_text(encoding="utf-8") == "{not json"  # never overwritten with an empty queue


@pytest.mark.parametrize("text", ['{"entries": null}', "[]", '{"entries": [1, {"url": 2}, {"state": "x"}]}'])
def test_a_queue_file_of_another_shape_reads_as_empty(ws, text):
    f = store.folder(ws) / "queue.json"
    f.parent.mkdir(parents=True)
    f.write_text(text, encoding="utf-8")
    assert store.read(ws) == []


def test_a_queue_file_that_stays_unreadable_is_refused_after_retries(ws, monkeypatch):
    f = store.folder(ws) / "queue.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"entries": []}', encoding="utf-8")
    tries = []

    def locked(self, *a, **k):  # Windows: the file is being replaced right now
        tries.append(1)
        raise PermissionError(13, "in use")

    monkeypatch.setattr(store.Path, "read_text", locked)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    with pytest.raises(Refused, match="cannot be read right now. Try again"):
        store.read(ws)
    assert len(tries) == 20


def test_a_queue_file_unreadable_once_is_read_again(ws, monkeypatch):
    store.add(ws, url(1), None, "human:p", login="bot")
    real, tries = store.Path.read_text, []

    def once(self, *a, **k):
        tries.append(1)
        if len(tries) == 1:
            raise PermissionError(13, "in use")
        return real(self, *a, **k)

    monkeypatch.setattr(store.Path, "read_text", once)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    assert [r["number"] for r in store.read(ws)] == [1]


def test_a_damaged_group_list_says_where_it_is(ws):
    f = store.folder(ws) / "groups.json"
    f.parent.mkdir(parents=True)
    f.write_text("nope", encoding="utf-8")
    with pytest.raises(Refused, match="group list is damaged"):
        store.groups(ws)


# -- the CLI -----------------------------------------------------------------------------------------------
def test_the_cli_finds_the_workspace_from_a_subfolder_with_umlauts(odd_ws, monkeypatch, capsys):
    sub = odd_ws / "Unterordner ß"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert cli.main(["queue", "list"]) == 0
    assert capsys.readouterr().out.strip() == "The merge queue is empty."
    store.add(odd_ws, url(1), None, "human:p", login="bot")
    assert cli.main(["queue", "list", "--json"]) == 0
    assert [r["number"] for r in json.loads(capsys.readouterr().out)["entries"]] == [1]


def test_outside_a_workspace_the_cli_says_what_to_do(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["queue", "list"]) == 2
    assert "Run orch init first" in capsys.readouterr().err


def test_a_refusal_with_json_is_on_stdout_too(ws, capsys):
    assert cli.main(["queue", "add", "https://github.com/acme/app/issues/3", "--json"]) == 2
    out = capsys.readouterr()
    assert "not a GitHub pull request address" in out.err
    assert "not a GitHub pull request address" in json.loads(out.out)["error"]


def test_an_unknown_ticket_is_a_plain_refusal_not_a_crash(ws, capsys):
    assert cli.main(["queue", "add", url(1), "--ticket", "NOPE-404"]) == 2
    assert capsys.readouterr().err.strip()
    assert store.read(ws) == []


def test_removing_what_does_not_wait_is_refused(ws, capsys):
    assert cli.main(["queue", "remove", url(1)]) == 2
    assert "does not wait in the merge queue" in capsys.readouterr().err


def test_the_queue_check_with_nothing_waiting_is_fine(ws, capsys):
    assert cli.main(["queue", "check"]) == 0
    assert "fine" in capsys.readouterr().out


def test_the_queue_check_says_when_entries_wait_without_a_runner(ws, monkeypatch, capsys):
    store.add(ws, url(1), None, "human:p", login="bot")
    monkeypatch.setattr(cli, "runner_alive", lambda root: False)
    assert cli.main(["queue", "check"]) == 1
    assert "1 pull requests wait and no merge queue runner" in capsys.readouterr().out


def test_an_audit_of_no_hours_is_refused(ws, capsys):
    assert cli.main(["queue", "audit", "--hours", "0"]) == 2
    assert "--hours" in capsys.readouterr().err


def test_refresh_of_an_unknown_ticket_is_refused(ws, capsys):
    assert cli.main(["act", "refresh", "NOPE-1"]) == 2
    assert "There is no ticket NOPE-1" in capsys.readouterr().err


@pytest.mark.parametrize(
    "env, want",
    [({"ORCH_AGENT": "claude code/../x"}, "agent:claude_code_.._x"), ({"ORCH_RUN": "r1"}, "agent:helper")],
)
def test_the_actor_name_is_safe_to_write(monkeypatch, env, want):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert cli._actor() == want


def test_a_person_with_an_umlaut_user_name_is_a_safe_actor(monkeypatch):
    monkeypatch.setattr(cli.getpass, "getuser", lambda: "jürg müller")
    assert cli._actor() == "human:j_rg_m_ller"

    def fails():
        raise OSError("no user")

    monkeypatch.setattr(cli.getpass, "getuser", fails)
    assert cli._actor() == "human:user"


def test_start_runner_passes_a_workspace_path_with_umlauts_as_one_argument(odd_ws, monkeypatch):
    seen = {}

    class Popen:
        def __init__(self, argv, cwd, **kw):
            seen.update(argv=argv, cwd=cwd)

    monkeypatch.setattr(cli.subprocess, "Popen", Popen)
    monkeypatch.setattr(cli, "runner_alive", lambda root: False)
    cli.start_runner(odd_ws)
    assert seen["argv"][-2:] == ["--root", str(odd_ws)] and seen["cwd"] == odd_ws
    assert (store.folder(odd_ws) / "runner.log").is_file()


# -- the watcher -------------------------------------------------------------------------------------------
def test_a_watcher_that_dies_at_its_start_is_said_plainly(odd_ws, monkeypatch):
    seen = {}

    class Dead:
        def __init__(self, argv, cwd, **kw):
            seen.update(argv=argv, cwd=cwd)

        def poll(self):
            return 1

    monkeypatch.setattr(service, "still_on", lambda root: True)
    monkeypatch.setattr(service.subprocess, "Popen", Dead)
    with pytest.raises(Refused, match="did not start. See .*watch.log"):
        service.start(odd_ws)
    assert seen["argv"][-2:] == ["--root", str(odd_ws.resolve())] and "-I" in seen["argv"]


def test_a_watcher_lock_with_a_garbled_owner_names_no_pid(ws):
    lock = service._lock(ws)
    lock.mkdir(parents=True)
    (lock / "owner").write_text("not-a-pid", encoding="utf-8")
    assert service.running_pid(ws) is None


def test_the_watcher_keeps_going_when_it_cannot_tell_whether_the_add_on_is_on(ws, monkeypatch):
    from orch import addons

    def broken(root):
        raise RuntimeError("config being written")

    monkeypatch.setattr(addons, "active", broken)
    assert service.still_on(ws) is True


def test_one_bad_round_never_ends_the_watcher(ws, monkeypatch):
    monkeypatch.setattr(service, "still_on", lambda root: True)
    said, n = [], []

    def tend():
        n.append(1)
        raise ValueError("x" * 500)

    assert service.watch(ws, tend, sleep=lambda s: None, rounds=2, log=said.append) == 0
    assert len(n) == 2 and said[1] == "Merge when green: ValueError: " + "x" * 200


# -- the group copy, real git in a folder with spaces and umlauts -------------------------------------------
def test_a_group_is_built_in_a_folder_with_spaces_and_umlauts(odd_ws, origin):
    git = Git(store.folder(odd_ws), REPO, url=str(origin))
    heads = git.fetch("develop", [1, 2])
    sha, included, conflicted = git.build(heads["base"], [(1, heads["1"]), (2, heads["2"])])
    assert included == [1, 2] and conflicted == []
    assert git.sources(sha, ["b.txt", "c.txt", "missing.txt", ""]) == {"b.txt": "b\n", "c.txt": "c\n"}
    assert git.sources(sha, []) == {}
    out = odd_ws / "Export ä"
    git.export(sha, out)
    assert sorted(p.name for p in out.iterdir()) == ["a.txt", "b.txt", "c.txt", "shared.txt"]


def test_git_errors_are_plain_refusals(ws, origin, monkeypatch):
    git = Git(store.folder(ws), REPO, url=str(origin))
    with pytest.raises(Refused, match="git fetch failed"):
        git.fetch("no-such-branch", [])
    git.fetch("develop", [])
    with pytest.raises(Refused, match="git archive failed"):
        git.export("0" * 40, ws / "out")
    with pytest.raises(Refused, match="git rev-parse failed"):
        git._sha("refs/queue/none")


def test_git_that_does_not_finish_in_time_is_refused(ws, origin, monkeypatch):
    git = Git(store.folder(ws), REPO, url=str(origin))

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(Refused, match="did not finish in time"):
        git.run("status")
    with pytest.raises(Refused, match="git archive did not finish in time"):
        git.export("0" * 40, ws / "out")


def test_no_git_is_said_plainly(ws, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(Refused, match="needs git"):
        Git(store.folder(ws), REPO)


def test_a_copy_git_cannot_remove_is_pruned_once_its_folder_is_gone(ws, origin):
    git = Git(store.folder(ws), REPO, url=str(origin))
    git.fetch("develop", [])
    gone = ws / "never made ä"
    git.worktree_remove(gone)  # git refuses (no such copy): the folder is gone, prune runs
    assert not gone.exists()


# -- the Pull requests page's state file (prs.json) --------------------------------------------------------
def test_the_page_state_is_saved_while_the_page_reads_it_on_windows(odd_ws, monkeypatch):
    from orch import procs

    data = poll.load(odd_ws)
    poll.save(odd_ws, data)
    real, tries = poll.os.replace, []

    def busy_once(src, dst):  # Windows: the page holds prs.json open for a moment
        tries.append(1)
        if len(tries) == 1:
            raise PermissionError(13, "in use")
        return real(src, dst)

    monkeypatch.setattr(procs, "_FILE_BUSY", True)
    monkeypatch.setattr(procs.os, "replace", busy_once)
    data["polled_at"] = "2026-11-25T10:00:00Z"
    poll.save(odd_ws, data)
    assert len(tries) == 2 and poll.load(odd_ws)["polled_at"] == "2026-11-25T10:00:00Z"
    assert not [p for p in poll.state_file(odd_ws).parent.iterdir() if p.name.startswith(".prs-")]


@pytest.mark.parametrize(
    "text", ["{broken", '{"schema": "other/1"}', '{"schema": "%s", "repos": [], "prs": 1}']
)
def test_a_damaged_page_state_starts_empty(odd_ws, text):
    f = poll.state_file(odd_ws)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text.replace("%s", poll.SCHEMA), encoding="utf-8")
    got = poll.load(odd_ws)
    assert got["schema"] == poll.SCHEMA and got["repos"] == {} and got["prs"] == {}


def test_an_oversized_page_state_is_not_read(ws, monkeypatch):
    monkeypatch.setattr(poll, "MAX_STATE", 10)
    poll.save(ws, {"schema": poll.SCHEMA, "polled_at": "x", "repos": {}, "prs": {}})
    assert poll.load(ws)["polled_at"] is None


# -- the Pull requests page's read (prread) ----------------------------------------------------------------
def _answer(rc=0, out="", err=""):
    return lambda args: subprocess.CompletedProcess(args, rc, out, err)


@pytest.mark.parametrize(
    "err, want",
    [
        ("To get started with GitHub CLI, please run:  gh auth login", prread.NOT_SIGNED_IN),
        ("GraphQL: Could not resolve to a Repository with the name 'acme/app'.", "does not exist"),
        ("API rate limit exceeded", "read limit"),
        ("connection reset", "tries again in a minute"),
    ],
)
def test_a_failed_read_says_why_in_plain_words(err, want):
    with pytest.raises(prread.GhError, match=want):
        prread.fetch(REPO, run=_answer(1, err=err))


@pytest.mark.parametrize("repo", ["", "acme", "acme/app/x", "../etc/passwd", "acme/app; rm -rf /"])
def test_only_a_repository_name_is_read(repo):
    with pytest.raises(prread.GhError, match="not a GitHub repository name"):
        prread.fetch(repo, run=_answer())


def test_an_answer_orch_cannot_read_is_said(monkeypatch):
    with pytest.raises(prread.GhError, match="cannot read"):
        prread.fetch(REPO, run=_answer(out="<html>"))
    errs = json.dumps({"errors": [{"message": "Could not resolve to a Repository"}]})
    with pytest.raises(prread.GhError, match="does not exist"):
        prread.fetch(REPO, run=_answer(out=errs))
    with pytest.raises(prread.GhError, match="could not be read just now"):
        prread.fetch(REPO, run=_answer(out="[]"))


def test_no_pull_requests_is_an_empty_answer():
    got = prread.fetch(REPO, [0, -1, 10**9, "7"], run=_answer(out=json.dumps({"data": {"repository": {}}})))
    assert got == {"open": [], "linked": {}}


def test_no_gh_or_a_slow_gh_is_one_plain_sentence(monkeypatch):
    monkeypatch.setattr(prread.shutil, "which", lambda name: None)
    with pytest.raises(prread.GhError, match="install gh"):
        prread._gh(["api"])
    monkeypatch.setattr(prread.shutil, "which", lambda name: sys.executable)

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1)

    monkeypatch.setattr(prread.subprocess, "run", slow)
    with pytest.raises(prread.GhError, match="did not answer in time"):
        prread._gh(["api"])

    def gone(*a, **k):
        raise FileNotFoundError(2, "gh")

    monkeypatch.setattr(prread.subprocess, "run", gone)
    with pytest.raises(prread.GhError, match="install gh"):
        prread._gh(["api"])
