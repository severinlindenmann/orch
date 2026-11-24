"""Usage page scenario USG-1: a stand-in account switcher with three made-up subscriptions, one API credit added to
the accounts file the way a person does it, the real dashboard, and a browser that changes every rule of the page once
(limit, a refused limit, order, on/off, end date and back, How work is spread, Switch by itself). Each click is checked
on the machine with `orch usage list` / `history`. Then Usage switches by itself and back, and its warning shows once on
Home until Got it. Browser half: dash_usage_page.cjs. Found in the clean e2e of Usage (ORCH-893)."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib import Skip, check, scenario, wait_for
from scenarios_look import _real_home, find_node, find_pw_dir

# Stand-in for the account switcher (`cswap list --json`, schemaVersion 1): reads and writes one state file, logs
# every call. Made-up addresses only; Usage keeps a hash and the part before the @.
SWITCHER = """#!/usr/bin/env python3
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
s = os.path.join(d, "accounts.json")
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
st = json.load(open(s))
a = sys.argv[1:]
if a[:1] == ["list"]:
    print(json.dumps(st))
elif a[:1] in (["switch"], ["enable"]):
    for r in st["accounts"]:
        if a[0] == "switch":
            r["active"] = r["number"] == int(a[1])
    json.dump(st, open(s, "w"))
else:
    sys.exit(2)
"""


def _iso(hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(five: dict[int, float], active: int = 1) -> dict:
    rows = []
    for n, (mail, org) in enumerate([("maria@example.com", ""), ("team@example.org", "Northwind Labs"),
                                     ("backup@example.net", "")], start=1):
        rows.append({"number": n, "email": mail, "organizationName": org, "isOrganization": bool(org),
                     "active": n == active, "usageFetchedAt": _iso(0), "usageStatus": "ok",
                     "usage": {"fiveHour": {"pct": five.get(n, 5), "resetsAt": _iso(3)},
                               "sevenDay": {"pct": 20, "resetsAt": _iso(70)}}})
    return {"schemaVersion": 1, "accounts": rows}


def _accounts(e, ws) -> dict:
    got = e.orchj(ws, "usage", "list")
    rows = got["accounts"] if isinstance(got, dict) else got
    return {r["label"]: r for r in rows}


def _history(e, ws) -> str:
    return e.orch(ws, "usage", "history")[1]


@scenario("USG-1", slow=True)
def usg1(e):
    """Usage page: limit, refused limit, order, on/off, end date and Keep it, no end, a ready-made spread and Switch by
    itself each work with one click and land in the history; Usage switches by itself to the next account and back, and
    its warning shows once on Home until Got it; pictures at 1440 and 390."""
    pw, node = find_pw_dir(), find_node(e.path)
    if not pw or not (Path(pw) / "playwright").is_dir() or not node:
        raise Skip("playwright or node not installed (set PW_DIR to a node_modules folder)")
    ws = e.ws("Usage")
    fake = e.tmp / "usg1-switcher"
    fake.mkdir(exist_ok=True)
    (fake / "cswap").write_text(SWITCHER)
    (fake / "cswap").chmod(0o755)
    state = fake / "accounts.json"
    state.write_text(json.dumps(_state({1: 40, 2: 8, 3: 0})))
    saved = e.env.get("ORCH_USAGE_SWITCHER")
    e.env["ORCH_USAGE_SWITCHER"] = str(fake / "cswap")  # orch start passes it on to the Usage add-on
    try:
        for a in ("dashboard", "usage"):
            rc, out, err = e.addon_add(ws, a)
            check(rc == 0, f"addon add {a}: {(err or out)[-300:]}")
        check(wait_for(lambda: len(_accounts(e, ws)) == 3, 60), f"the 3 subscriptions never showed: {_accounts(e, ws)}")
        # an API credit, added to the accounts file by hand (Usage has no Add button for it)
        spend = fake / "spend.jsonl"
        spend.write_text(json.dumps({"t": _iso(-1), "account": "openai", "usd": 2.5}) + "\n")
        # Usage keeps one accounts file per computer user, in orch's home (ORCH-943); the workspace folder only
        # without orch's home
        acc = next((p for p in (e.orch_home / "usage" / "accounts.json",
                                Path(e.path_of(ws)) / ".orch" / "addons" / "usage" / "accounts.json") if p.is_file()),
                   e.orch_home / "usage" / "accounts.json")
        data = json.loads(acc.read_text())
        data["accounts"].append({"id": "a_usg1ai", "label": "OpenAI credit", "type": "api-key", "provider": "openai",
                                 "source": {"reader": "spend-log", "path": str(spend), "name": "openai"},
                                 "on": True, "order": 4, "rule": {"limits": [], "for": [], "ends": None},
                                 "prev": None})
        acc.write_text(json.dumps(data, indent=1))
        e.orch(ws, "usage", "limit", "OpenAI", "$25", "--period", "month")
        e.orch(ws, "usage", "limit", "maria", "90%", "--period", "5h")
        check(len(_accounts(e, ws)) == 4, "the hand-added API credit is not listed")

        e.orch(ws, "start", "--no-open")
        url = next((a["url"] for r in e.orchj(ws, "status") for a in r["addons"] if a["addon"] == "dashboard"), "")
        check(url, "the dashboard did not start")
        launch = next((x["url"] for x in e.orchj(ws, "start", "--print-launch-url").get("launch") or []
                       if x.get("addon") == "dashboard"), "")
        check("#launch=" in launch, "orch start printed no sign-in link for the dashboard")
        shots = os.environ.get("E2E_SHOTS", "")
        real = _real_home()
        cache = next((str(c) for c in (real / "Library/Caches/ms-playwright", real / ".cache/ms-playwright") if c.is_dir()), "")
        env = {**e.env, "PW_DIR": pw, **({"PLAYWRIGHT_BROWSERS_PATH": cache} if cache else {})}
        script = Path(__file__).parent / "dash_usage_page.cjs"
        rc, out, err = e.sh([node, str(script), url, launch, "page", shots], env=env, timeout=300)
        check(rc == 0, f"browser half (page) failed: {(err or out)[-800:]}")
        got = json.loads(out.strip().splitlines()[-1])
        check(not got["errors"] and got["noOverflow"], f"page errors or a cut-off layout: {got}")
        check("at most 100%" in got["refused"], f"a limit of 150% was not refused in plain words: {got['refused']}")

        # what the page did, checked on the machine itself
        rows = _accounts(e, ws)
        maria = rows["maria"]
        check([x["value"] for x in maria["rule"]["limits"]] == [85], f"maria's limit after the page: {maria['rule']}")
        check(rows["backup"]["order"] == 2, f"backup was not moved up: {rows['backup']}")
        check(rows["OpenAI credit"]["on"] is False, "the API credit was not turned off")
        check(maria["rule"]["ends"] is None, f"Keep it, no end left an end: {maria['rule']}")
        hist = _history(e, ws)
        for words in ("limit 85% (5 hours)", "order 3 to 2", "turned off", "rule kept, no end",
                      "How work is spread: Even spread", "switching turned on"):
            check(words in hist, f"history has no line '{words}':\n{hist[:1200]}")
        check("ends" in hist, f"the end date set in the page is not in the history:\n{hist[:800]}")

        # Switch by itself: maria past her 5-hour limit -> the next account in order (backup); room again -> back
        state.write_text(json.dumps(_state({1: 96, 2: 8, 3: 0}, active=1)))
        check(wait_for(lambda: "switch 3" in (fake / "calls.log").read_text(), 90),
              f"Usage never switched to backup: {(fake / 'calls.log').read_text()[-300:]}")
        check(wait_for(lambda: "switched to backup" in _history(e, ws), 30), "no history line for the switch")
        time.sleep(1)
        state.write_text(json.dumps(_state({1: 10, 2: 8, 3: 0}, active=3)))
        check(wait_for(lambda: "switched to maria" in _history(e, ws), 420),
              f"Usage never switched back to maria:\n{_history(e, ws)[:600]}")

        # the warning: every account at or near its limit -> one row on Home, gone after Got it
        e.orch(ws, "usage", "limit", "backup", "50%", "--period", "5h")
        e.orch(ws, "usage", "limit", "Northwind", "50%", "--period", "5h")
        state.write_text(json.dumps(_state({1: 96, 2: 97, 3: 98}, active=1)))
        check(wait_for(lambda: "every account" in e.orch(ws, "usage", "needs")[1], 90),
              "the all-at-limit warning never showed")
        launch = next((x["url"] for x in e.orchj(ws, "start", "--print-launch-url").get("launch") or []
                       if x.get("addon") == "dashboard"), "")  # a sign-in link works once: a new one for Home
        rc, out, err = e.sh([node, str(script), url, launch, "home", shots], env=env, timeout=300)
        check(rc == 0, f"browser half (home) failed: {(err or out)[-800:]}")
        check("Nothing needs you" in e.orch(ws, "usage", "needs")[1], "Got it on Home did not hide the warning")
        check("warning seen" in _history(e, ws), "no history line for Got it")
    finally:
        e.sh(["orch", "stop", "--all"], cwd=e.path_of(ws))
        if saved is None:
            e.env.pop("ORCH_USAGE_SWITCHER", None)
        else:
            e.env["ORCH_USAGE_SWITCHER"] = saved
        time.sleep(0.5)
