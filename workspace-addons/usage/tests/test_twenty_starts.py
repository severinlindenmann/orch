"""The try of the whole spread (ORCH-661): in a throwaway workspace the owner sets a share by command, 20 helper starts
are picked through `orch usage pick`, they land on two subscriptions, an API credit and Codex as the share says, each
start says why, a subscription at its limit is skipped, and the Usage page shows the day's spread."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta

from conftest import jrun

from orch_usage import cli as usage_cli
from orch_usage import page, picker, sources

# 20 helper starts as orch would ask for them: kind of work and orch's model pick
STARTS = [
    ("lead", "opus"), ("code", "sonnet"), ("reviews", "sonnet"), ("code", "sonnet"), ("helpers", "sonnet"),
    ("code", "opus"), ("scripts", "haiku"), ("code", "sonnet"), ("lead", "opus"), ("reviews", "sonnet"),
    ("code", "sonnet"), ("helpers", "sonnet"), ("code", "sonnet"), ("reviews", "opus"), ("lead", "opus"),
    ("code", "sonnet"), ("scripts", "haiku"), ("code", "sonnet"), ("builds", "sonnet"), ("reviews", "sonnet"),
]  # fmt: skip


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.00+00:00")


def _switcher(first_5h=20.0):
    """Two subscriptions, both on pace with their own week (30 % used, about 74 % allowed by now)."""
    now = datetime.now(UTC)
    week_reset = _iso(now + timedelta(days=3, hours=12))

    def acct(n, addr, h):
        return {
            "number": n,
            "email": addr,
            "organizationName": f"{addr}'s Organization",
            "organizationUuid": f"0000000{n}-0000-0000-0000-000000000000",
            "isOrganization": True,
            "active": n == 1,
            "usageStatus": "ok",
            "usage": {
                "fiveHour": {"pct": h, "resetsAt": _iso(now + timedelta(hours=2))},
                "sevenDay": {"pct": 30.0, "resetsAt": week_reset, "willLastToReset": True},
            },
            "threshold": 99.9,
            "loginExpiresAt": _iso(now + timedelta(days=5)),
            "usageFetchedAt": _iso(now),
        }

    return {
        "schemaVersion": 1,
        "activeAccountNumber": 1,
        "accounts": [acct(1, "first@example.test", first_5h), acct(2, "second@example.test", 10.0)],
    }


def _seed(cli, ws, fake_switcher, tmp_path):
    fake_switcher.answer(_switcher())
    jrun(cli, "list")  # the readers find the two subscriptions
    log = tmp_path / "spend.jsonl"
    log.write_text("")
    p = ws / ".orch/addons/usage/accounts.json"
    data = json.loads(p.read_text())
    for id_, label, type_, provider, order, limit in (
        ("a_key001", "Claude API credit", "api-key", "anthropic-api", 3, 50),
        ("a_cdx001", "Codex", "helper-tool", "openai", 4, 30),
    ):
        data["accounts"].append(
            {
                "id": id_,
                "label": label,
                "type": type_,
                "provider": provider,
                "source": {"reader": "spend-log", "path": str(log), "name": id_},
                "on": True,
                "order": order,
                "rule": {
                    "limits": [{"value": limit, "unit": "$", "period": "month"}],
                    "for": [],
                    "ends": None,
                },
                "prev": None,
            }
        )
    p.write_text(json.dumps(data))
    return {a["label"]: a["id"] for a in data["accounts"]}


def test_twenty_starts_follow_the_owners_share(cli, ws, fake_switcher, tmp_path):
    ids = _seed(cli, ws, fake_switcher, tmp_path)
    first, second = ids["first"], ids["second"]

    # the owner sets the share by command: the even spread (reviews and scripts on API credit, one in 4 code on
    # Codex, 70 % of a subscription's week by Wednesday)
    code, d = jrun(cli, "share", "--preset", "even", "--by", "human:owner")
    assert code == 0, d
    assert (
        "one in 4 Code tickets on Codex" in d["sentence"]
        and "Reviews and Scripts on API credit" in d["sentence"]
    )

    picks = []
    for i, (kind, model) in enumerate(STARTS, 1):
        if i == 11:  # half way the first subscription reaches its 5-hour limit
            fake_switcher.answer(_switcher(first_5h=100.0))
        code, p = jrun(
            cli, "pick", "--start", f"s{i:02}", "--ticket", f"T-{i}", "--kind", kind, "--model", model
        )
        assert code == 0, p
        assert jrun(cli, "started", p["start"])[1]["ok"] is True
        picks.append((i, kind, p))

    by = Counter(p["source"] for _, _, p in picks)
    # the share: 4 reviews + 2 scripts on API credit; code starts 4 and 8 on Codex; the rest on the subscriptions,
    # the first until it is at its limit, then the second
    assert by == {first: 6, second: 6, ids["Claude API credit"]: 6, ids["Codex"]: 2}
    for i, kind, p in picks:
        assert p["why"].startswith(f"runs on {p['label']}: "), p["why"]  # every start says why
        if kind in ("reviews", "scripts"):
            assert p["source"] == "a_key001" and "work goes to API credit" in p["why"]
            assert p["tool"] == "claude" and p["dollars"] > 0
        elif p["source"] == "a_cdx001":
            assert (
                kind == "code" and "one in 4 code starts goes to Codex" in p["why"] and p["tool"] == "codex"
            )
        elif i <= 10:
            assert p["source"] == first and "first in the order" in p["why"]
        else:  # the first subscription is at its limit: skipped, and the reason says so
            assert p["source"] == second and "skipped: first" in p["why"] and "first with room" in p["why"]
            assert p["dollars"] == 0  # a subscription is paid already
    codex_code = [i for i, k, p in picks if k == "code" and p["source"] == "a_cdx001"]
    assert codex_code == [8, 18]  # the 4th and the 8th code start

    # a retry of a start gets the same answer and counts once
    code, again = jrun(cli, "pick", "--start", "s03", "--kind", "reviews", "--model", "sonnet")
    assert again["repeat"] is True and again["source"] == "a_key001"
    for i in range(1, 21):
        assert jrun(cli, "finished", f"s{i:02}", "--spent", "unknown" if i % 5 == 0 else "0.80")[1]["ok"]

    # the Usage page shows the day's spread
    m = page.build(usage_cli.gather(ws), ws)
    sp = m["spread"]
    rows = {r["id"]: r for r in sp["sources"]}
    assert sp["starts"] == 20
    assert {k: rows[k]["starts"] for k in rows} == {first: 6, second: 6, "a_key001": 6, "a_cdx001": 2}
    assert rows[first]["pct"] == 30 and rows["a_cdx001"]["pct"] == 10
    assert rows[first]["skipped"] and "next account takes its work" in rows[first]["skipped"]
    assert rows[second]["skipped"] is None
    assert rows[first]["dollars"] is None and rows["a_key001"]["dollars"] > 0  # money only where it costs
    assert set(rows["a_key001"]["kinds"]) == {"Reviews", "Scripts"} and rows["a_cdx001"]["kinds"] == ["Code"]
    assert m["share"]["preset"] == "even"
    assert str(tmp_path) not in json.dumps(m)  # labels and numbers only: no file path of a reader


def test_a_source_at_its_limit_is_skipped_and_nothing_left_makes_the_start_wait(
    cli, ws, fake_switcher, tmp_path
):
    ids = _seed(cli, ws, fake_switcher, tmp_path)
    jrun(cli, "share", "--preset", "even")
    # the API credit has spent its month: review work falls back in order, past the empty credit
    log = tmp_path / "spend.jsonl"
    log.write_text(json.dumps({"t": datetime.now(UTC).isoformat(), "account": "a_key001", "usd": 50}) + "\n")
    code, p = jrun(cli, "pick", "--start", "r1", "--kind", "reviews", "--model", "sonnet")
    assert code == 0 and p["source"] == ids["first"]
    assert "Claude API credit at its limit" in p["why"]
    # every source off or full: the start waits, with the reason and when to try again
    fake_switcher.answer(_switcher(first_5h=100.0))
    for acc in ("second", "Codex"):
        assert jrun(cli, "off", acc)[0] == 0
    code, p = jrun(cli, "pick", "--start", "r2", "--kind", "code", "--model", "sonnet")
    assert code == 3 and p["wait"] is True and p["why"].startswith("waits: no account has room")
    assert p["until"]  # the first subscription's 5-hour reset
    code, out, _ = cli("pick", "--start", "r3", "--kind", "lead")
    assert code == 3 and out.startswith("Waits: no account has room") and "Tries again at" in out


def test_the_share_in_the_pickers_words():
    rows = [{"id": "b", "order": 2}, {"id": "a", "order": 1}]
    assert sources.picker_share(None, rows) == {"order": ["a", "b"]}
    s = {"week_pct": 70, "by_day": "wednesday", "api_for": ["reviews"], "codex_one_in": 4, "when_ahead": "codex",
         "day_dollars": 0}  # fmt: skip
    assert sources.picker_share(s, rows) == {
        "order": ["a", "b"],
        "credit_kinds": ["reviews"],
        "one_in": {"tool": "codex", "every": 4},
        "week": {"wed": 70},
        "ahead_to": "tool",
        "ahead_dollars_day": None,
        "ahead_tool": "codex",
    }
    assert "week" not in sources.picker_share({**s, "week_pct": 100}, rows)
    assert "ahead_to" not in sources.picker_share({**s, "when_ahead": "none"}, rows)


def test_ahead_goes_where_the_share_says_and_a_subscription_ahead_of_its_own_week_waits_its_turn(tmp_path):
    at = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    start = picker._iso(at - timedelta(days=2))  # its own week began 2 days ago: about 58 % allowed by now
    subs = [
        {"id": "s1", "label": "First", "tool": "claude", "type": "subscription", "week_used": 80.0, "week_start": start},
        {"id": "s2", "label": "Second", "tool": "claude", "type": "subscription", "week_used": 20.0, "week_start": start},
        {"id": "k1", "label": "API credit", "tool": "claude", "type": "api-key", "left": 100.0},
        {"id": "c1", "label": "Codex", "tool": "codex", "type": "helper-tool", "left": 100.0},
    ]  # fmt: skip
    share = {"order": ["s1", "s2", "k1", "c1"], "week": {"wed": 70}, "ahead_to": "tool", "ahead_tool": "codex"}
    p = picker.pick(tmp_path, {"start": "x1", "kind": "lead"}, share, subs, at)
    assert p.source == "s2" and "First is ahead of its week (80% used" in p.why  # the one on pace goes first
    both_ahead = [{**s, "week_used": 90.0} if s["type"] == "subscription" else s for s in subs]
    p = picker.pick(tmp_path, {"start": "x2", "kind": "lead"}, share, both_ahead, at)
    assert p.source == "c1" and "ahead of the week" in p.why  # when_ahead codex: no dollar cap
    p = picker.pick(tmp_path, {"start": "x3", "kind": "lead"}, {**share, "ahead_to": "api", "ahead_dollars_day": 10},
                    both_ahead, at)  # fmt: skip
    assert p.source == "k1" and "of $10 for that used today" in p.why
    p = picker.pick(tmp_path, {"start": "x4", "kind": "reviews"}, {"order": ["c1", "k1"], "credit_kinds": ["reviews"]},
                    subs, at)  # fmt: skip
    assert p.source == "k1"  # review work goes to the API credit first, Codex only as a fallback
