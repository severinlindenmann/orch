"""A short check after every update (ORCH-551): does the new install still do the everyday things? What each
add-on that is on declares in its manifest ([[selfcheck]]: the Factory list, the merge queue runner ...), the
sign-in of each running page server and the page of every add-on. Each probe runs the newly installed `orch`
as a child process (core never imports add-on code or names an add-on), so a broken add-on shows up here and
not later in a person's face.

When a probe fails after an update that moved to a newer release, orch keeps one card for Home: "Go back to
release N-1?" (the release this update came from). Yes runs `orch update --to <N-1>` (ORCH-550). The card is
machine-wide (one file in the orch home), like the auto-update note."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from orch import addons

CARD = "update-check.json"
TIMEOUT = 60
KEEP_DAYS = 14

# A probe runner: (argv after `orch`, root) -> (exit code, stdout). Tests replace it.
Runner = Callable[[list[str], Path], tuple[int, str]]


def run_orch(argv: list[str], root: Path) -> tuple[int, str]:
    try:
        from orch import procs

        p = subprocess.run(  # noqa: S603 - our own interpreter and module, fixed argv
            procs.orch_python_argv(*argv),
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 124, str(e)
    return p.returncode, p.stdout


def _json(out: str):
    try:
        return json.loads(out)
    except ValueError:
        return None


def _http(url: str, body: dict | None = None, origin: str | None = None) -> int:
    """The answer code of a GET (or a JSON POST) to this computer; 0 when nothing answers."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    headers = {"Content-Type": "application/json", **({"Origin": origin} if origin else {})}
    if body is not None:  # like the page's own fetch: a page server may refuse a POST without it (Insights)
        headers["Sec-Fetch-Site"] = "same-origin"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=15) as r:  # noqa: S310 - loopback only
            return r.status
    except HTTPError as e:
        return e.code
    except OSError:
        return 0


def _loopback(url: object) -> bool:
    return isinstance(url, str) and url.startswith(
        ("http://127.0.0.1:", "http://localhost:", "http://[::1]:")
    )


def _running_pages(root: Path) -> dict[str, str]:
    """{add-on: address} of every page server running for this workspace (Usage too, not only those a person
    signs in to)."""
    from orch import services

    want = str(Path(root).resolve())
    out = {}
    for e in services.running():
        same = isinstance(e.get("workspace"), str) and str(Path(e["workspace"]).resolve()) == want
        if same and isinstance(e.get("addon"), str) and _loopback(e.get("url")):
            out[e["addon"]] = e["url"].rstrip("/")
    return out


def _page_servers(root: Path) -> list[tuple[str, str]]:
    """(name, address) of the page servers running for this workspace that a person signs in to."""
    from orch import pagelaunch

    return sorted((n, u) for n, u in _running_pages(root).items() if n in pagelaunch.LAUNCH_SERVERS)


def _answers(url: str, http=_http, page: bool = False) -> bool:
    """Does this address answer (below 500; a page: 200, it opens without a sign-in)? It was just restarted:
    give it a moment to come up."""
    for i in range(10):
        code = http(url)
        if (code == 200) if page else (0 < code < 500):
            return True
        if i < 9:
            time.sleep(2)
    return False


def _sign_in(root: Path, server: str, base: str, http) -> int:
    """Sign in the way the page does: a fresh one-time token handed to POST /session. Only when a person ran
    the update (a helper never signs in as the person); the token is spent here and never printed."""
    from orch import pagelaunch, tickets

    if tickets.agent_tool() is not None and not pagelaunch.is_test_workspace(root):
        return -1
    token = pagelaunch.write_launch_token(root, server)
    return http(f"{base}/session", {"token": token}, base)


def _signs_in(root: Path, server: str, base: str, http=_http, sign_in=_sign_in) -> str | None:
    if not _answers(f"{base}/", http):
        return f"the {server} page does not answer"
    code = sign_in(root, server, base, http)
    if code in (-1, 200):  # -1: a helper ran the update, the page answering is what can be checked
        return None
    return f"{server} sign-in failed (answer {code or 'none'})"


def _active(root: Path, run: Runner) -> list[dict] | None:
    rc, out = run(["addon", "list", "--json"], root)
    got = _json(out) if rc == 0 else None
    if not isinstance(got, list):
        return None
    return [
        a for a in got if isinstance(a, dict) and a.get("active") is True and isinstance(a.get("name"), str)
    ]


def _declared(root: Path, run: Runner, name: str, entry: dict) -> str | None:
    """One [[selfcheck]] entry of an add-on's manifest: `orch <name> <args>` must end well (and give JSON
    when it asks for --json)."""
    args = [str(x) for x in entry.get("args") or []]
    rc, out = run([name, *args], root)
    ok = rc == 0 and ("--json" not in args or _json(out) is not None)
    return None if ok else str(entry.get("fails") or f"{entry.get('label') or name} does not work")


def _page(root: Path, run: Runner, a: dict, base: str | None = None, answers=_answers) -> str | None:
    """One add-on page. An add-on with its own page server (Insights, Usage) is shown in a frame and has no
    view to pull: its running server must answer on its page (ORCH-1582); when it does not run here (it starts
    when opened), its command must load. A dashboard tab without a page server: the view it pulls."""
    name = a["name"]
    page = a.get("page")
    if page and base:
        path = page.get("path") if isinstance(page, dict) and isinstance(page.get("path"), str) else "/"
        ok = answers(base + "/" + path.lstrip("/"), page=True)
    elif isinstance(a.get("dashboard"), dict) and not page:
        rc, out = run([name, "view", "--json"], root)
        ok = rc == 0 and isinstance(_json(out), dict)
    else:
        rc, _ = run([name, "--help"], root)
        ok = rc == 0
    return None if ok else f"the {name} page does not answer"


def run_checks(
    root: Path,
    run: Runner = run_orch,
    servers=_page_servers,
    signs_in=_signs_in,
    pages=_running_pages,
    answers=_answers,
) -> list[dict]:
    """[{"name", "ok", "why"}] for each probe that applies here: what each add-on that is on declares in its
    manifest ([[selfcheck]]), the sign-in of each running page server, and each add-on page."""
    results: list[dict] = []

    def add(name: str, why: str | None) -> None:
        results.append({"name": name, "ok": why is None, "why": why or ""})

    on = _active(root, run)
    if on is None:
        add("add-ons", "the add-on list does not open")
        return results
    on = sorted(on, key=lambda a: a["name"])
    for a in on:
        for entry in a.get("selfcheck") or []:
            if isinstance(entry, dict):
                add(str(entry.get("label") or a["name"]), _declared(root, run, a["name"], entry))
    for server, base in servers(root):
        add(f"{server.capitalize()} sign-in", signs_in(root, server, base))
    running = pages(root)
    for a in on:
        if a.get("dashboard") or a.get("page"):
            add(f"{a['name']} page", _page(root, run, a, running.get(a["name"]), answers))
    return results


def card_path() -> Path:
    return addons.home() / CARD


def after_update(
    root: Path,
    old_release: int | str | None,
    new_release: int | str | None,
    run: Runner = run_orch,
    servers=_page_servers,
    pages=_running_pages,
) -> list[str]:
    """Run the checks after an update and keep (or clear) the Home card. Returns the lines `orch update`
    prints.
    The card offers going back only when this update moved to a newer release; a failed check after going
    back (or on a development build) is reported without that offer."""
    try:
        results = run_checks(root, run, servers, pages=pages)
    except Exception as e:  # noqa: BLE001 - a broken check must never break the update itself
        results = [{"name": "self-check", "ok": False, "why": f"the check itself failed: {e}"[:200]}]
    failed = [r for r in results if not r["ok"]]
    if not failed:
        card_path().unlink(missing_ok=True)
        return [f"Self-check: all {len(results)} checks passed."] if results else []
    from orch import updateinfo

    old, new = updateinfo.as_version(old_release), updateinfo.as_version(new_release)
    back = old if (old and new and updateinfo.vkey(old) < updateinfo.vkey(new)) else None
    addons._write_atomic(
        card_path(),
        json.dumps(
            {
                "at": int(time.time()),
                "root": str(Path(root).resolve()),
                "release": new,
                "back_to": back,
                "failed": [{"name": r["name"], "why": r["why"]} for r in failed],
            }
        ),
    )
    lines = ["Self-check after the update found a problem:", *[f"  - {r['why']}" for r in failed]]
    if back:
        lines.append(f"Go back to release {back} with: orch update --to {back}")
    return lines


def card() -> dict | None:
    """The Home card while it is fresh: {"at", "release", "back_to", "failed": [{"name", "why"}]}."""
    try:
        d = json.loads(card_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("failed"), list) or not isinstance(d.get("at"), int):
        return None
    if time.time() - d["at"] > KEEP_DAYS * 86400:
        return None
    from orch import updateinfo

    return {
        "at": d["at"],
        "release": updateinfo.as_version(d.get("release")),
        "back_to": updateinfo.as_version(d.get("back_to")),
        "failed": [
            {"name": str(f.get("name", ""))[:80], "why": str(f.get("why", ""))[:200]}
            for f in d["failed"][:10]
            if isinstance(f, dict)
        ],
    }


def dismiss() -> None:
    card_path().unlink(missing_ok=True)
