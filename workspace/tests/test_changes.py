"""`orch changes --since <date|tag>`: done tickets by kind with their evidence links (release notes)."""

import json
import os
import subprocess

from orch import tickets


def make(
    proj, title, status="done", done="2026-11-10T09:00:00Z", kind=None, urls=(), line="Status review -> done"
):
    t = tickets.create(proj, title, "human:t")
    raw = tickets.load(proj, t["id"])
    raw["status"] = status
    evidence = [{"type": "url", "ref": u} for u in urls] + [{"type": "note", "ref": "not a link"}]
    raw["checklist"] = [{"id": "c1", "text": "do it", "done": True, "evidence": evidence}]
    raw["history"].append({"at": done, "by": "human:t", "via": "cli", "text": line})
    if kind:
        raw["kind"] = {"name": kind, "by": "human:t"}
    tickets._write(proj, raw)
    return tickets.load(proj, t["id"])


def test_done_tickets_since_a_date_grouped_by_kind(proj, run):
    run("init", "--yes")
    pr = "https://github.com/o/r/pull/7"
    f = make(proj, "Export to CSV", kind="feature", urls=[pr, pr, "https://example.com/doc"])
    b = make(proj, "Fix the login", kind="bug", done="2026-11-12T09:00:00Z")
    n = make(proj, "Patched by hand", line="Patched status (status review -> done)")
    make(proj, "Too early", kind="feature", done="2026-10-01T09:00:00Z")
    make(proj, "Still in check", status="review", kind="feature")

    code, out, _ = run("changes", "--since", "2026-11-01", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["count"] == 3
    assert [(g["kind"], [r["id"] for r in g["tickets"]]) for g in data["groups"]] == [
        ("bug", [b["id"]]),
        ("feature", [f["id"]]),
        (None, [n["id"]]),
    ]
    assert data["groups"][1]["tickets"][0]["urls"] == [pr, "https://example.com/doc"]

    code, out, _ = run("changes", "--since", "2026-11-01")
    assert code == 0
    assert "Changes since 2026-11-01 (3 tickets)" in out
    assert out.index("Bug") < out.index("New feature") < out.index("Kind not set")
    assert f"- {f['key']}  Export to CSV\n  {pr}" in out
    assert "Too early" not in out and "Still in check" not in out and "not a link" not in out
    assert "Next:" in out

    code, out, _ = run("changes", "--since", "2026-12-01")
    assert code == 0 and "No tickets were done since 2026-12-01." in out


def test_since_a_git_tag_and_a_wrong_value(proj, run):
    run("init", "--yes")
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-11-05T12:00:00Z",
        "GIT_COMMITTER_DATE": "2026-11-05T12:00:00Z",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    for c in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "r1"], ["tag", "release-1"]):
        subprocess.run(["git", *c], cwd=proj, env=env, check=True)
    old = make(proj, "Before the tag", done="2026-11-04T09:00:00Z")
    new = make(proj, "After the tag", done="2026-11-06T09:00:00Z")

    code, out, _ = run("changes", "--since", "release-1", "--json")
    assert code == 0
    ids = [r["id"] for g in json.loads(out)["groups"] for r in g["tickets"]]
    assert ids == [new["id"]] and old["id"] not in ids

    code, out, err = run("changes", "--since", "no-such-tag")
    assert code != 0 and "neither a date nor a git tag" in out + err
