"""Services tab scenario SVC-1: real background jobs on this machine (launchd on macOS, systemd --user on Linux), the
real dashboard, and a browser that presses every button of the tab once. Browser half: dash_services_tab.cjs."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

from lib import Skip, check, free_port, scenario, wait_for
from scenarios_look import find_node, find_pw_dir, _real_home

IDS = ("svc1-web", "svc1-ticker")


def _answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _rows(e, ws) -> dict:
    got = e.orchj(ws, "services", "list")
    rows = got["services"] if isinstance(got, dict) else got
    return {r["id"]: r for r in rows}


@scenario("SVC-1", local_only=True)
def svc1(e):
    """Services tab: two real services (a web preview with a health check made by a ticket, a ticker added by hand)
    show with every row field; Stop, Start, Restart (list row and panel), the Starts-by-itself switch, Made by, Open log,
    Remove (Keep it, then Remove) and Open Automation each work with one click; pictures at 1280, 1920 and 390."""
    pw, node = find_pw_dir(), find_node(e.path)
    if not pw or not (Path(pw) / "playwright").is_dir() or not node:
        raise Skip("playwright or node not installed (set PW_DIR to a node_modules folder)")
    linux = {}
    if sys.platform.startswith("linux"):
        # The user's service manager reads units only from its own home and is reached over the user's bus (env -i
        # drops both), so orch needs the account's real HOME here. Only on a throwaway CI machine, never on a dev box.
        if os.environ.get("CI") != "true":
            raise Skip("on Linux SVC-1 needs the account's real home: it runs only in CI")
        bus = Path(f"/run/user/{os.getuid()}")
        check((bus / "bus").exists(), "no user bus: turn on linger for the CI user first")
        linux = {"HOME": str(_real_home()), "XDG_RUNTIME_DIR": str(bus), "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}/bus"}
    ws = e.ws("Services")
    # before the add-ons: `addon add dashboard` already starts the dashboard, and a dashboard started without the
    # user's bus says "the service manager of your account is not running" (orch start keeps it as it is)
    saved = {k: e.env.get(k) for k in linux}
    e.env.update(linux)
    port = free_port(set())
    tick = ["services", "add", "Ticker", "--id", IDS[1], "--start", "--", "sh", "-c",
            "while true; do echo tick $(date +%H:%M:%S); sleep 1; done"]
    try:
        for a in ("dashboard", "automation", "services"):
            rc, out, err = e.addon_add(ws, a)
            check(rc == 0, f"addon add {a}: {(err or out)[-300:]}")
        tid = e.orchj(ws, "ticket", "new", "Preview the site")["id"]
        web = ["services", "add", "Web preview", "--id", IDS[0], "--port", str(port), "--ticket", tid, "--auto",
               "--start", "--", "python3", "-m", "http.server", str(port), "--bind", "127.0.0.1"]
        e.orch(ws, *web)
        e.orch(ws, *tick)
        check(wait_for(lambda: _answers(port), 30), "the web preview never answered on its port")
        e.orch(ws, "services", "check", ok=False)  # the health check result shows on the row
        e.orch(ws, "start", "--no-open")
        url = next((a["url"] for r in e.orchj(ws, "status") for a in r["addons"] if a["addon"] == "dashboard"), "")
        check(url, "the dashboard did not start")
        launch = next((x["url"] for x in e.orchj(ws, "start", "--print-launch-url").get("launch") or []
                       if x.get("addon") == "dashboard"), "")
        check("#launch=" in launch, "orch start printed no sign-in link for the dashboard")
        shots = os.environ.get("E2E_SHOTS", "")  # a folder for the pictures (run.sh passes it through)
        real = _real_home()
        cache = next((str(c) for c in (real / "Library/Caches/ms-playwright", real / ".cache/ms-playwright") if c.is_dir()), "")
        env = {**e.env, "PW_DIR": pw, **({"PLAYWRIGHT_BROWSERS_PATH": cache} if cache else {})}
        script = Path(__file__).parent / "dash_services_tab.cjs"
        rc, out, err = e.sh([node, str(script), url, launch, str(port), tid, shots], env=env, timeout=300)
        check(rc == 0, f"browser half failed: {(err or out)[-800:]}")
        got = json.loads(out.strip().splitlines()[-1])
        # what the page did, checked on the machine itself
        rows = _rows(e, ws)
        check(IDS[1] not in rows, f"Remove left the ticker in the list: {sorted(rows)}")
        check(rows.get(IDS[0], {}).get("state") == "running", f"web preview after the clicks: {rows.get(IDS[0])}")
        check(_answers(port), "the web preview does not answer after Start")
        check(set(got["facts"]) >= {"State", "Starts by itself", "Made by", "Health check"}, f"row fields {got['facts']}")
        check(got["log"], "the ticker's log lines did not show")
        check(not got["errors"] and got["noOverflow"], f"page errors or a cut-off layout: {got}")
    finally:
        for sid in IDS:  # leave no job on this machine, whatever failed
            e.orch(ws, "services", "remove", sid, ok=False)
        e.sh(["orch", "stop", "--all"], cwd=ws)
        for k, v in saved.items():
            if v is None:
                e.env.pop(k, None)
            else:
                e.env[k] = v
        time.sleep(0.5)
    check(not _answers(port), "the web preview still answers after the clean-up")
