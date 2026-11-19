"""Merge queue and release keeper scenario QUEUE-1 (ORCH-894): the real `orch pull-requests queue` and `orch github
release` commands against a fake GitHub (fake_github.py: a local git repository and a fake `gh`), no network.

What a person does and sees: the queue empty, wrong addresses and drafts refused, GitHub not answering refused,
four pull requests added, one taken out while it waits, one merged in a group of its own, two checked together
in a group whose full checks fail, the group split, the good one merged and the bad one dropped with its helper
woken; the audit; the release keeper's dry run and a security review it starts for a pull request that touches the
relay, with a wrong commit refused and a "problems" verdict putting a card on the role ticket."""

from __future__ import annotations

import json
from pathlib import Path

import fake_github as fg
from lib import check, scenario, wait_for

REPO = "https://github.com/acme/app/pull/"
FAKE_HELPER = """#!/bin/sh
# a helper that never calls a model: it notes how it was started and waits a moment
echo "$(date +%s) $*" >> "$HOME/fake-claude.log"
case "$1" in --version|-v) echo "2.0.1 (Claude Code)"; exit 0;; --help|auth) exit 0;; esac
sleep 20
"""


def _queue(e, ws) -> dict[int, dict]:
    rows = e.orchj(ws, "pull-requests", "queue", "list")
    rows = rows.get("entries", rows) if isinstance(rows, dict) else rows
    out: dict[int, dict] = {}
    for r in rows:  # newest entry of each pull request wins
        out[int(r["number"])] = r
    return out


@scenario("QUEUE-1", slow=True, local_only=True)
def mq1(e):
    """Merge queue end to end against a fake GitHub: add, list, remove, audit, a group of one, a group, a red group
    split, a dropped pull request waking its helper; release keeper dry run and a security review start."""
    home = Path(e.env["HOME"])
    fg.setup(home, "bot", fakebin=e.bin)
    e.env["FAKE_GH_STATE"] = str(home / "fakegh" / "state.json")
    e.env["FAKE_GH_CHECK_SECS"] = "3"
    helper = e.bin / "claude"
    helper.write_text(FAKE_HELPER, encoding="utf-8")
    helper.chmod(0o755)
    ws = e.ws("Queue")
    rc, out, err = e.addon_add(ws, "pull-requests")
    check(rc == 0, f"addon add pull-requests: {(err or out)[-300:]}")
    # orch's own setting (ORCH-545): pull requests run light checks, the full set runs on queue groups. With the
    # default (merge_alone on) a member of a red group is merged on its light checks: issue 1912.
    cfg = e.path_of(ws) / ".orch" / "config.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\n[pull_requests]\nmerge_alone = false\n", encoding="utf-8")
    tids = {n: e.orchj(ws, "ticket", "new", f"Change {n}")["id"] for n in (1, 2, 3, 4)}
    for n, tid in tids.items():
        e.orch(ws, "ref", "add", tid, f"{REPO}{n}")

    # empty and refused
    _, out, _ = e.orch(ws, "pull-requests", "queue", "list")
    check("empty" in out, f"an empty queue says so: {out!r}")
    rc, out, err = e.orch(ws, "pull-requests", "queue", "add", "https://github.com/acme/app/issues/3", ok=False)
    check(rc == 2 and "not a GitHub pull request address" in out + err, f"an issue address is refused: {out}{err}")
    rc, out, err = e.orch(ws, "pull-requests", "queue", "add", f"{REPO}5", ok=False)
    check(rc == 2 and "draft" in out + err, f"a draft is refused: {out}{err}")
    fg.change(home, down=True)
    rc, out, err = e.orch(ws, "pull-requests", "queue", "add", f"{REPO}1", "--ticket", tids[1], ok=False)
    check(rc == 2 and "did not show" in out + err, f"GitHub not answering is refused: {out}{err}")
    fg.change(home, down=False)
    check(_queue(e, ws) == {}, "nothing was queued while refused")

    # four in, one out while it waits
    for n in (1, 2, 3, 4):
        e.orch(ws, "pull-requests", "queue", "add", f"{REPO}{n}", "--ticket", tids[n])
    _, out, _ = e.orch(ws, "pull-requests", "queue", "add", f"{REPO}4", "--ticket", tids[4])
    check("Already in the merge queue" in out, f"a second add says it is there already: {out!r}")
    rc, out, err = e.orch(ws, "pull-requests", "queue", "remove", f"{REPO}4", ok=False)
    check(rc == 0 and "Taken out" in out, f"a waiting pull request can be taken out: {out}{err}")

    # the runner merges #1 and #2, drops #3 (its group's full checks fail) and wakes #3's helper
    def settled() -> bool:
        q = _queue(e, ws)
        return all(q.get(n, {}).get("state") in ("merged", "out") for n in (1, 2, 3))

    check(wait_for(settled, 900, 5), f"the queue did not finish: {_queue(e, ws)}")
    q = _queue(e, ws)
    check(q[1]["state"] == "merged" and q[2]["state"] == "merged", f"#1 and #2 merged: {q}")
    check(q[3]["state"] == "out", f"#3 left the queue: {q[3]}")
    check(q[4]["state"] == "out", f"#4 stays out: {q[4]}")
    log = (e.path_of(ws) / ".orch" / "addons" / "pull-requests" / "runner.log").read_text(encoding="utf-8")
    check("Group https://github.com/acme/app/pull/" in log, f"a group was built: {log[-600:]}")
    check("The group was red" in log, f"the red group was split: {log[-600:]}")
    state = json.loads((home / "fakegh" / "state.json").read_text(encoding="utf-8"))
    check(state["prs"]["3"]["state"] == "OPEN", "the dropped pull request was never merged")
    groups = [p for p in state["prs"].values() if str(p["head"]).startswith("orch-queue/")]
    check(groups and all(p["state"] != "OPEN" for p in groups), f"no group pull request is left open: {groups}")

    def woken() -> bool:
        _, shown, _ = e.orch(ws, "ticket", "show", tids[3])
        started = home / "fake-claude.log"
        return "left the merge queue" in shown and started.exists() and "--session-id" in started.read_text()

    check(wait_for(woken, 60, 1), "the dropped pull request's helper was not woken")
    _, out, _ = e.orch(ws, "pull-requests", "queue", "audit")
    check("Merge queue from" in out, f"the audit answers: {out!r}")

    # release keeper: off, then a dry run, then a security review for a pull request that touches the relay
    _, out, _ = e.orch(ws, "github", "release", "--dry-run")
    check("off here" in out, f"the keeper says it is off: {out!r}")
    e.sh(["git", "clone", "-q", "https://github.com/acme/app.git", str(e.tmp / "acme-clone")], check_rc=True)
    sha0 = e.sh(["git", "--git-dir", str(home / "fakegh" / "acme-app.git"), "rev-list", "--max-parents=0",
                 "develop"], check_rc=True)[1].strip()  # fmt: skip
    e.sh(["git", "--git-dir", str(home / "fakegh" / "acme-app.git"), "update-ref", "refs/heads/main", sha0],
         check_rc=True)  # fmt: skip
    role = e.orchj(ws, "ticket", "new", "Releases")["id"]
    for k, v in (("release_keeper", role), ("release_repo", "acme/app"), ("release_clone", str(e.tmp / "acme-clone"))):
        e.orch(ws, "config", "set", f"github.{k}", v)
    fg.open_pr(home, 6, "feat/relay-auth", "Relay: check the sign-in token", {"relay/src/auth.rs": "// x\n"})
    _, out, _ = e.orch(ws, "github", "release", "--dry-run")
    check("Dry run" in out and "#6: would start a security review" in out, f"the dry run names the review: {out!r}")
    check(not any("Security review" in t["title"] for t in e.orchj(ws, "ticket", "list")), "a dry run writes nothing")
    _, out, _ = e.orch(ws, "github", "release")
    check("#6: security review" in out, f"the keeper starts the review: {out!r}")
    check(any(t["title"].startswith("Security review: pull request #6") for t in e.orchj(ws, "ticket", "list")),
          "the review ticket is there")  # fmt: skip
    rc, out, err = e.orch(ws, "review", "security", "6", "ok", "fine", "--sha", "0000000", ok=False)
    check(rc == 2 and "--sha" in out + err, f"a verdict for another commit is refused: {out}{err}")
    head = e.sh(["git", "--git-dir", str(home / "fakegh" / "acme-app.git"), "rev-parse", "feat/relay-auth"],
                check_rc=True)[1].strip()  # fmt: skip
    e.orch(ws, "review", "security", "6", "problems", "the token is compared with ==", "--sha", head)
    e.orch(ws, "github", "release")
    _, out, _ = e.orch(ws, "review", "list")
    check("security review of pull request #6" in out, f"a problems verdict puts a card up: {out!r}")
