"""ORCH-2170 (RP2, RP7, RP9): the Publish page connects from the admin's pasted text, each row carries your
note, the ticket and when it ends, and with publish down the page lists the local record at once."""

import io
import json

import pytest
from conftest import turn_on
from fakes import WS

from orch import net, publish
from orch.errors import Refused

ADMIN_TEXT = """Hi! Here is how to connect.

Connect this workspace to orch-publish. Run in the project folder:
  orch addon add publish --yes
  orch publish connect {url} --workspace {ws} --token {token}
If orch is not installed yet:
  macOS/Linux: curl -fsSL {url}/onboarding.sh | sh -s -- --workspace {ws} --token {token}
  Windows: & ([scriptblock]::Create((irm {url}/onboarding.ps1))) -Workspace {ws} -Token {token}
Thanks!
"""


def test_the_connect_line_is_found_in_the_whole_pasted_text():
    text = ADMIN_TEXT.format(url="https://publish.example.test", ws="ws_pilatus001", token="orp_" + "a" * 43)
    assert publish.parse_connect_text(text) == (
        "https://publish.example.test",
        "ws_pilatus001",
        "orp_" + "a" * 43,
    )
    # quotes, flag=value, other order, a quote left open by a copy: still the same three values
    odd = '> orch publish connect --token="orp_x1" --workspace \'ws_a\' "https://p.test/orch'
    assert publish.parse_connect_text(odd) == ("https://p.test/orch", "ws_a", "orp_x1")


@pytest.mark.parametrize(
    "text, says",
    [
        ("Hello, nothing useful here", "did not find a connect line"),
        ("orch publish connect https://p.test --workspace ws_a", "cut off"),
        ("orch relay connect https://r.test --workspace ws_a --token orn_x", "for the relay"),
    ],
)
def test_a_text_without_a_usable_line_says_what_to_do_and_never_prints_the_token(text, says):
    with pytest.raises(Refused, match=says) as e:
        publish.parse_connect_text(text)
    assert "orn_x" not in str(e.value)


def test_paste_connects_through_the_same_path_as_the_command(proj, run, pub, monkeypatch):
    text = ADMIN_TEXT.format(url=pub.url, ws=WS, token=pub.token)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    code, out, err = run("publish", "connect", "--paste")
    assert code == 0 and "Connected to" in out and "orch publish file <path>" in out, (out, err)
    cfg = json.loads((proj / ".orch/secrets/publish.json").read_text())
    assert (cfg["url"], cfg["workspace"], cfg["token"]) == (pub.url, WS, pub.token)


def test_connect_without_values_says_how(proj, run):
    turn_on(proj, "publish")
    code, _, err = run("publish", "connect")
    assert code == 2 and "orch publish connect --paste" in err


def test_a_row_carries_note_ticket_and_when_it_ends(proj, run, pub, new_ticket, monkeypatch):
    from test_publish_client import connect

    connect(run, pub)
    tid = new_ticket("Spring campaign landing page")
    (proj / "plan.txt").write_text("x")
    fid = json.loads(run("publish", "file", "plan.txt", "--note", "Draft plan", "--ticket", tid, "--json")[1])["id"]
    import datetime as dt

    end = (dt.datetime.now(dt.UTC) + dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")  # the fake's date is past
    monkeypatch.setattr(
        publish, "_all_files", lambda *a, **k: [{"id": fid, "name": "plan.txt", "size": 1, "expires_at": end}]
    )
    row = publish.view(proj)["blocks"][0]["items"][0]
    assert row["subtitle"] == "“Draft plan”"
    assert row["meta"][0].endswith("Spring campaign landing page") and row["meta"][0] != " "
    assert row["meta"][1].startswith("Ends in ") and "chips" not in row


def test_a_row_without_note_or_ticket_says_so_and_a_link_ending_soon_is_marked(proj, run, pub, monkeypatch):
    import datetime as dt

    from test_publish_client import connect

    connect(run, pub)
    (proj / "price.pdf").write_text("x")
    fid = json.loads(run("publish", "file", "price.pdf", "--json")[1])["id"]
    soon = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    publish._remember(proj, fid, expires_at=soon)
    _down(monkeypatch)  # the record is what the page lists now
    row = publish.view(proj)["blocks"][0]["items"][0]
    assert row["subtitle"] == "No note" and row["meta"] == [" "]
    assert row["chips"] == [{"label": row["chips"][0]["label"], "tone": "warn"}]
    assert row["chips"][0]["label"] in ("Ends today", "Ends tomorrow")


def test_ends_in_plain_words():
    import datetime as dt

    def at(**kw):
        return (dt.datetime.now(dt.UTC) + dt.timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert publish.ends(at(days=7)) == ("Ends in 7 days", False)
    assert publish.ends(at(days=2, hours=3)) == ("Ends in 3 days", False)
    text, soon = publish.ends(at(hours=3))
    assert soon and text in ("Ends today", "Ends tomorrow")
    assert publish.ends(at(hours=30))[1] is False
    assert publish.ends(at(seconds=-5)) == ("Ended", False)
    assert publish.ends(None) == ("Kept until you delete it", False)


def _down(monkeypatch):
    seen = []

    def refuse(req, timeout, **kw):
        seen.append(timeout)
        raise OSError("no route to host")

    monkeypatch.setattr(net.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(net.time, "sleep", lambda s: seen.append(("slept", s)))
    return seen


def test_offline_the_page_lists_the_local_record_and_says_publish_cannot_be_reached(proj, run, pub, monkeypatch):
    from test_publish_client import connect

    connect(run, pub)
    for name in ("plan.txt", "price.pdf"):
        (proj / name).write_text("x")
        fid = json.loads(run("publish", "file", name, "--note", "n " + name, "--json")[1])["id"]
        publish._remember(proj, fid, expires_at="2099-01-01T00:00:00Z")
    seen = _down(monkeypatch)
    v = publish.view(proj)
    assert seen and all(isinstance(s, float) or isinstance(s, int) for s in seen)  # no sleeping between tries
    assert v["notice"].startswith("Publish can't be reached.") and "until it is back" in v["notice"]
    items = v["blocks"][0]["items"]
    assert {i["title"] for i in items} == {"plan.txt", "price.pdf"}
    assert "No shared links" not in json.dumps(v)  # never, while local links exist


def test_offline_with_nothing_recorded_does_not_claim_there_are_no_links(proj, run, pub, monkeypatch):
    from test_publish_client import connect

    connect(run, pub)
    _down(monkeypatch)
    v = publish.view(proj)
    assert v["blocks"][0]["items"] == [] and "No shared links" not in json.dumps(v)
    assert v["notice"].startswith("Publish can't be reached.")


def test_the_cli_list_quick_falls_back_and_plain_list_says_publish_cannot_be_reached(proj, run, pub, monkeypatch):
    from test_publish_client import connect

    connect(run, pub)
    (proj / "a.txt").write_text("x")
    json.loads(run("publish", "file", "a.txt", "--json")[1])
    _down(monkeypatch)
    code, out, _ = run("publish", "list", "--quick", "--json")
    assert code == 0 and json.loads(out)["unreachable"] is True
    code, _, err = run("publish", "list")
    assert code == 2 and err.startswith("Refused: Publish can't be reached right now.")
    assert "Try again in a few minutes" in err
