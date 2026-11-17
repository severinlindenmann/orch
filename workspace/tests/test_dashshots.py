"""ORCH-312: CI takes the proof pictures of a dashboard change; `orch ask --ci-shots` shows them on a card.
Which pages a change touches, the list CI writes, its checks, the page the card shows, `orch shot --page`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orch import cli_shot, dashshots
from orch.errors import Refused

WEB = dashshots.WEB
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


@pytest.mark.parametrize(
    "files, pages",
    [
        ([WEB + "pages/home.css"], ["home"]),
        ([WEB + "pages/ticket.js", WEB + "pages/review.js"], ["ticket", "review"]),
        ([WEB + "pages/newticket.js"], ["home"]),
        ([WEB + "app.js"], list(dashshots.PAGES)),
        (["workspace/src/orch_ui/static/widgets.css"], list(dashshots.PAGES)),
        ([WEB + "pages/livebar.js"], list(dashshots.PAGES)),  # shows on every page
        ([dashshots.SERVER + "data.py"], list(dashshots.PAGES)),  # the data every page shows
        (["workspace-addons/dashboard/tests/test_x.py", "docs/a.md", "relay/src/main.rs"], []),
        ([], []),
    ],
)
def test_pages_for(files, pages):
    assert dashshots.pages_for(files) == pages


def _ci_folder(tmp_path: Path, pages=("home", "ticket"), head="a" * 40) -> Path:
    d = tmp_path / "ci"
    d.mkdir()
    for p in pages:
        for w in dashshots.WIDTHS:
            (d / dashshots.file_name(p, w)).write_bytes(PNG)
    m = dashshots.manifest(head, 7, list(pages), d)
    (d / "manifest.json").write_text(json.dumps(m))
    return d


def test_manifest_lists_each_page_at_three_widths(tmp_path):
    d = _ci_folder(tmp_path)
    m = json.loads((d / "manifest.json").read_text())
    assert m["schema"] == dashshots.SCHEMA and m["head"] == "a" * 40 and m["pr"] == 7
    assert [p["page"] for p in m["pages"]] == ["home", "ticket"]
    assert m["pages"][0]["files"] == {"1280": "dashboard-home-1280.png", "1920": "dashboard-home-1920.png",
                                      "390": "dashboard-home-390.png"}  # fmt: skip
    rows = dashshots._check_manifest(m, d)
    assert rows[1]["label"] == "A ticket" and rows[1]["files"][390] == "dashboard-ticket-390.png"


@pytest.mark.parametrize(
    "spoil",
    [
        lambda m, d: m.update(schema="other"),
        lambda m, d: m["pages"][0].update(page="evil"),
        lambda m, d: m["pages"][0]["files"].update({"1280": "../../etc/passwd"}),
        lambda m, d: m["pages"][0]["files"].update({"640": "dashboard-home-1280.png"}),
        lambda m, d: (d / "dashboard-home-1280.png").write_bytes(b"<html>not a picture"),
        lambda m, d: (d / "dashboard-home-1280.png").unlink(),
        lambda m, d: m.update(pages=[]),
    ],
)
def test_a_bad_list_from_ci_is_refused(tmp_path, spoil):
    d = _ci_folder(tmp_path)
    m = json.loads((d / "manifest.json").read_text())
    spoil(m, d)
    with pytest.raises(Refused):
        dashshots._check_manifest(m, d)


def test_the_sheet_holds_every_picture_inline(tmp_path):
    d = _ci_folder(tmp_path)
    rows = dashshots._check_manifest(json.loads((d / "manifest.json").read_text()), d)
    page = dashshots.sheet_html("Pull request #7: <changed>", rows, d, "Taken by CI.")
    assert page.count('src="data:image/png;base64,') == 6
    assert "&lt;changed&gt;" in page and "<changed>" not in page
    assert "Phone · 390 px" in page and "Wide screen · 1920 px" in page and "Desktop · 1280 px" in page
    assert "prefers-color-scheme: dark" in page and "http" not in page.replace("http-equiv", "")


def _fake_github(monkeypatch, folder: Path, head="a" * 40, runs="11\tcompleted\n", artifact="99"):
    calls = []

    def gh(args, timeout=30):
        calls.append(args)

        class R:
            returncode = 0
            stderr = ""
            stdout = ""

        r = R()
        if args[:2] == ["pr", "view"]:
            r.stdout = head + "\n"
        elif args[0] == "api" and "actions/runs?" in args[1]:
            r.stdout = runs
        elif args[0] == "api" and args[1].endswith("/artifacts"):
            r.stdout = artifact
        elif args[:2] == ["run", "download"]:
            dest = Path(args[args.index("-D") + 1])
            for f in folder.iterdir():
                (dest / f.name).write_bytes(f.read_bytes())
        return r

    monkeypatch.setattr(dashshots, "_gh", gh)
    return calls


PR = "https://github.com/owner/repo/pull/7"


def test_fetch_takes_the_pictures_of_the_newest_commit(tmp_path, monkeypatch):
    d = _ci_folder(tmp_path)
    calls = _fake_github(monkeypatch, d)
    m, rows = dashshots.fetch(PR, tmp_path / "dest")
    assert m["pr"] == 7 and len(rows) == 2
    assert (tmp_path / "dest" / "dashboard-ticket-390.png").read_bytes() == PNG
    assert ["run", "download", "11", "-R", "owner/repo", "-n", dashshots.ARTIFACT] == calls[3][:7]


def test_fetch_refuses_old_pictures_running_checks_and_none(tmp_path, monkeypatch):
    d = _ci_folder(tmp_path, head="b" * 40)
    _fake_github(monkeypatch, d)
    with pytest.raises(Refused, match="older commit"):
        dashshots.fetch(PR, tmp_path / "x")
    _fake_github(monkeypatch, d, runs="12\tin_progress\n")
    with pytest.raises(Refused, match="still taking"):
        dashshots.fetch(PR, tmp_path / "x")
    _fake_github(monkeypatch, d, artifact="")
    with pytest.raises(Refused, match="no dashboard pictures"):
        dashshots.fetch(PR, tmp_path / "x")
    with pytest.raises(Refused, match="pull request address"):
        dashshots.fetch("https://example.com/pull/7", tmp_path / "x")


def test_ask_ci_shots_puts_the_pictures_on_the_card(proj, run, tmp_path, monkeypatch):
    d = _ci_folder(tmp_path)
    _fake_github(monkeypatch, d)
    code, out, err = run("ticket", "new", "New Home look", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    code, out, err = run("ask", tid, "Does the new Home look right?", "--draft", "New Home look",
                         "--ci-shots", PR, "--then", "I merge it.", "--json", "--by", "agent:x")  # fmt: skip
    assert code == 0, out + err
    card = json.loads(out)["card"]
    assert card["preview"]["type"] == "page" and card["open"] == PR
    sheet = proj / ".orch" / "tickets" / tid / "artifacts" / "ci-pictures-pr7.html"
    assert sheet.read_text().count("data:image/png;base64,") == 6
    assert (sheet.parent / "ci-pictures-pr7" / "dashboard-home-1920.png").is_file()


@pytest.mark.parametrize(
    "extra",
    [
        ["--ci-shots", PR],  # not on a plain question
        ["--draft", "T", "--ci-shots", PR, "--file", "a.png", "--then", "x"],
        ["--choose", "T", "--option", "A=One", "--option", "B=Two", "--ci-shots", PR, "--then", "x"],
    ],
)
def test_ask_ci_shots_refusals(proj, run, extra):
    code, out, _ = run("ticket", "new", "T", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    code, out, _ = run("ask", tid, "Look", *extra, "--json", "--by", "agent:x")
    assert code == 2 and "--ci-shots" in out


def test_shot_pages():
    assert cli_shot.parse_pages("home, tickets,ticket=ticket/DM1-2") == [
        ("home", "home"), ("tickets", "tickets"), ("ticket", "ticket/DM1-2")]  # fmt: skip
    assert cli_shot.parse_pages(None) == []
    for bad in ("Home", "a=<x>", "a,a", "a=javascript:x"):
        with pytest.raises(Refused):
            cli_shot.parse_pages(bad)
    assert cli_shot.page_url("http://x:1/#launch=tok", "home") == "http://x:1/#home"


def test_shot_pages_sign_in_once_then_each_page_at_each_width(tmp_path, monkeypatch):
    from test_shot import fake_browser

    pipes = fake_browser(monkeypatch)
    files = cli_shot.shoot("http://x:1/#launch=tok", [1280, 390], tmp_path, "d", None, 1,
                           [("home", "home"), ("ticket", "ticket/DM1-2")])  # fmt: skip
    assert [f.name for f in files] == [
        "d-home-1280.png",
        "d-home-390.png",
        "d-ticket-1280.png",
        "d-ticket-390.png",
    ]
    urls = [p["url"] for m, p, _ in pipes[0][1].calls if m == "Page.navigate"]
    assert urls == ["http://x:1/#launch=tok", "http://x:1/#home", "http://x:1/#home",
                    "http://x:1/#ticket/DM1-2", "http://x:1/#ticket/DM1-2"]  # fmt: skip
    with pytest.raises(Refused):
        cli_shot.shoot(str(tmp_path / "f.html"), [1280], tmp_path, "d", None, 1, [("home", "home")])
