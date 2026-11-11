"""The 0909 Focus board changes that matter for safety. The page endpoint's headers and the POST origin fence are
asserted against a running server (test_proof_file.py, test_server.py); here the same is checked on a real page request
and the frame that shows the page."""

from pathlib import Path

import pytest

from .conftest import TID
from .test_server import req

WEB = Path(__file__).resolve().parents[1] / "src/orch_focus/web"


def test_agent_page_is_sandboxed_by_the_server_whoever_opens_it(server, ws):
    ev = ws / ".orch" / "tickets" / TID / "evidence"
    ev.mkdir(parents=True)
    (ev / "index.html").write_text("<script>1</script>")
    key = server.RequestHandlerClass.keywords["tracker"].view(TID)["page_key"]
    st, _, h = req(server, "GET", f"/page/{TID}/{key}/index.html")
    csp = h["Content-Security-Policy"]
    assert st == 200 and "sandbox allow-scripts" in csp and "allow-same-origin" not in csp
    assert h["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("origin", ["null", "http://evil.example"])
def test_a_sandboxed_page_cannot_post_to_the_board(server, fake_orch, origin):
    st, _, _ = req(server, "POST", "/api/act", {"op": "run.stop", "args": {"ticket": TID}}, {"Origin": origin})
    assert st == 403


def test_the_frame_has_no_same_origin_and_page_comes_first():
    proof = (WEB / "proof.js").read_text()
    assert "allow-same-origin" not in proof
    assert "sandbox: 'allow-scripts'" in proof
    assert proof.index("['Page', showPage]") < proof.index("['Code', showSource]")


def test_wont_do_board_emits_no_start_or_evidence():
    from orch_focus.board import TicketWatcher

    watcher = TicketWatcher("r_abc12345", TID)
    step = {"id": "c1", "text": "Review", "done": False, "state": "doing", "wont_do": True,
            "evidence": [{"type": "note", "text": "Old evidence"}]}
    ticket = {"checklist": [step]}
    assert watcher.feed(ticket) == []
    step.pop("wont_do")
    assert [e["kind"] for e in watcher.feed(ticket)] == ["task.start"]
    step["wont_do"] = True
    assert watcher.feed(ticket) == []
    assert watcher.feed(ticket) == []
