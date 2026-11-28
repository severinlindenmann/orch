"""`orch ticket export`: the ticket as a markdown handover to paste into any agent (R2.3, R5.2)."""

import json

from orch import tickets

TOKEN = "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0"  # built at run time


def _ticket(run):
    run("init", "--yes")
    key = json.loads(
        run("ticket", "new", "Write the launch post", "--done-when", "post is live", "--json")[1]
    )["key"]
    run("check", "add", key, "draft the text")
    run("check", "add", key, "publish it")
    run("check", "done", key, "c1", "--note", "draft in docs/post.md")
    run("ask", key, "Which day?", "--option", "Mon", "--option", "Tue", "--recommend", "Mon")
    run("ref", "add", key, "https://example.com/pull/1")
    run("ticket", "summary", key, "Draft done, the day is open.")
    return key


def test_export_is_a_markdown_handover_and_the_hint_stays_out_of_it(proj, run):
    key = _ticket(run)
    code, out, err = run("ticket", "export", key)
    assert code == 0, err
    assert out.startswith(f"# {key}: Write the launch post\n")
    for part in (
        "## Where it stands\n\nDraft done, the day is open.",
        "Done when: post is live",
        "- [x] c1 draft the text\n  - evidence: draft in docs/post.md",
        "- [ ] c2 publish it",
        "- q1: Which day? Options: Mon / Tue. Suggested: Mon.",
        "https://example.com/pull/1",
        f"orch ticket show {key}",
    ):
        assert part in out, part
    assert "Next:" not in out and err.startswith("Next: ")  # stdout pastes or redirects clean
    data = json.loads(run("ticket", "export", key, "--json")[1])
    assert data["markdown"] == out


def test_export_with_a_planted_secret_prints_nothing_and_names_the_line(proj, run):
    key = _ticket(run)
    path = tickets.ticket_path(proj, tickets.resolve(proj, key))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["checklist"][1]["text"] = f"publish with {TOKEN}"  # hand-edited or synced in: never scanned on save
    path.write_text(json.dumps(raw), encoding="utf-8")
    code, out, err = run("ticket", "export", key)
    assert code != 0 and out == ""
    assert "a GitHub token on line" in err and "nothing was shown" in err
    assert TOKEN not in err
