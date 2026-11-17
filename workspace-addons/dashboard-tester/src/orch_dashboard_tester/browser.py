"""The browser half of a pass: open every page at 1280, 1920 and 390 px and write down what is wrong. No AI.

Safety: it only opens addresses and reads. It never clicks, types or presses anything (no answer button, no card,
no Start, Merge, Allow, Save or Delete). The sign-in link is used once and never printed or logged; addresses in
findings are cut to the page part.
"""

from __future__ import annotations

import contextlib
import re
import time
from pathlib import Path

VIEWPORTS = (
    {"name": "desktop", "width": 1280, "height": 900},
    {"name": "wide", "width": 1920, "height": 1080},
    {"name": "phone", "width": 390, "height": 844},
)
SLOW_MS = 6000
EMPTY_MS = 20000
SAFE_ARGS = ["--use-mock-keychain", "--password-store=basic"]  # no keychain password window on macOS
LEAK = r"\b(undefined|NaN|null)\b|\[object Object\]|Traceback \(most recent"

# Longest text of the page: the dashboard's loading shape (aria-busy skeleton) or a short "Loading" counts as empty.
TEXT_LEN_JS = """() => {
  const m = document.querySelector('main') || document.body;
  const t = m ? m.innerText.trim() : '';
  if (document.querySelector('.skeleton-page[aria-busy="true"]')) return 0;
  return /Loading|Checking…/.test(t) && t.length < 80 ? 0 : t.length;
}"""

PROBE_JS = """({never, leak}) => {
  const vw = window.innerWidth;
  const out = {hscroll: document.documentElement.scrollWidth - vw, cut: [], words: [], leaks: [], textLen: 0, text: ''};
  const m = document.querySelector('main');
  out.textLen = m ? m.innerText.trim().length : 0;
  out.text = (m ? m.innerText : document.body ? document.body.innerText : '').slice(0, 4000);
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  for (const el of document.querySelectorAll('button, a, h1, h2, h3, label, input, select, [role=tab]')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 2 && out.cut.length < 5) {
      // only when no scrolling parent holds it (a sideways list that scrolls on purpose is fine)
      let q = el.parentElement, scrolls = false;
      while (q && q !== document.body) { const o = getComputedStyle(q).overflowX;
        if (o === 'auto' || o === 'scroll') { scrolls = true; break; } q = q.parentElement; }
      if (!scrolls) out.cut.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40));
    }
  }
  const chrome = [...document.querySelectorAll('button, [role=tab], nav a, h1, h2, h3, label, th, .btn')]
    .filter(vis).map(e => (e.innerText || '').trim()).filter(Boolean);
  for (const w of never) {
    const re = new RegExp('(^|[^A-Za-z])' + w.replace(/[.*+?^${}()|[\\]\\\\-]/g, '\\\\$&') + '([^A-Za-z]|$)');
    const hit = chrome.find(t => re.test(t.replace(/\\bSign in\\b/g, '')));
    if (hit) out.words.push(w + ' in "' + hit.slice(0, 60) + '"');
  }
  const body = m ? m.innerText : document.body.innerText;
  const lk = new RegExp(leak);
  for (const line of body.split('\\n')) { if (lk.test(line) && out.leaks.length < 3) out.leaks.push(line.trim().slice(0, 80)); }
  return out;
}"""


def redact(text: str, base: str) -> str:
    s = re.sub(r"/go/[^/?#\s\"]+", "/go/XXX", str(text))
    s = re.sub(r"launch=[A-Za-z0-9_-]+", "launch=XXX", s)
    return s.replace(base, "") if base else s


def slug(route: str) -> str:
    return re.sub(r"\W+", "-", route).strip("-") or "page"


def launch(pw):
    """Playwright's own Chromium (the download `setup` makes), else Chrome or Chromium on this computer."""
    errors = []
    for how in ({}, {"channel": "chrome"}, {"channel": "chromium"}):
        try:
            return pw.chromium.launch(args=SAFE_ARGS, **how)
        except Exception as e:  # noqa: BLE001 - try the next browser
            errors.append(str(e).splitlines()[0][:120])
    raise RuntimeError(
        "No browser to look with. Run: orch dashboard-tester setup. (" + "; ".join(errors) + ")"
    )


def browser_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            launch(pw).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _text_len(page) -> int:
    best = 0
    for f in page.frames:  # add-on pages live in a frame inside main
        with contextlib.suppress(Exception):  # a frame that went away
            best = max(best, int(f.evaluate(TEXT_LEN_JS) or 0))
    return best


def _wait_main(page, timeout_ms: int) -> int:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < timeout_ms:
        if _text_len(page) > 20:
            return int((time.monotonic() - t0) * 1000)
        page.wait_for_timeout(250)
    return -1


def _probe(page, never: list[str]) -> dict | None:
    try:
        top = page.main_frame.evaluate(PROBE_JS, {"never": never, "leak": LEAK})
    except Exception:  # noqa: BLE001
        return None
    for f in page.frames:
        if f == page.main_frame:
            continue
        o = None
        with contextlib.suppress(Exception):  # a frame that went away
            o = f.evaluate(PROBE_JS, {"never": never, "leak": LEAK})
        if o is None:
            continue
        top["cut"] += o["cut"]
        top["words"] += o["words"]
        top["leaks"] += o["leaks"]
        if o["textLen"] > top["textLen"]:
            top["textLen"], top["text"] = o["textLen"], o["text"]
    top["textLen"] = max(top["textLen"], _text_len(page))
    return top


def findings_for(route: str, vp: dict, ms: int, pr: dict | None, shot: str) -> list[dict]:
    """What one page visit found (pure, tested without a browser)."""
    out: list[dict] = []
    base = {"route": route, "viewport": vp["name"], "shot": shot}
    if ms < 0 or (pr and pr["textLen"] < 20):
        out.append({**base, "key": f"empty|{route}|{vp['name']}", "severity": "big", "kind": "empty",
                    "text": f"{route} showed nothing within {EMPTY_MS // 1000} seconds"})  # fmt: skip
    elif ms > SLOW_MS:
        out.append({**base, "key": f"slow|{route}|{vp['name']}", "severity": "small", "kind": "slow",
                    "text": f"{route} took {ms / 1000:.1f} s to show its content", "ms": ms})  # fmt: skip
    if pr:
        if vp["name"] == "phone" and pr["hscroll"] > 4:
            out.append({**base, "key": f"hscroll|{route}", "severity": "small", "kind": "layout",
                        "text": f"{route} scrolls sideways at {vp['width']} px ({pr['hscroll']} px too wide)"})  # fmt: skip
        if pr["cut"]:
            out.append({**base, "key": f"cut|{route}|{vp['name']}", "severity": "small", "kind": "layout",
                        "text": f"{route} at {vp['width']} px: cut off at the right edge: {', '.join(pr['cut'])}"})  # fmt: skip
        for w in pr["words"]:
            out.append({**base, "key": f"word|{route}|{w.split(' in ')[0]}", "severity": "small", "kind": "word",
                        "text": f"{route}: word from the never-list on screen: {w}"})  # fmt: skip
        for line in pr["leaks"]:
            out.append({**base, "key": f"leak|{route}|{line[:30]}", "severity": "small", "kind": "word",
                        "text": f'{route}: program value on screen: "{line}"'})  # fmt: skip
    return out


def error_finding(e: dict, vp: dict, shots: Path) -> dict:
    sig = re.sub(r"\d+", "#", e["text"])[:80]
    big = e["kind"] == "pageerror" or re.match(r"^5\d\d ", e["text"]) is not None
    what = "request failed " if e["kind"] == "http" else "page error "
    return {"route": e["route"], "viewport": vp["name"], "shot": str(shots / f"{vp['name']}-{slug(e['route'])}.png"),
            "key": f"{e['kind']}|{e['route']}|{sig}", "severity": "big" if big else "small", "kind": e["kind"],
            "text": f"{e['route']}: {what}{e['text']}"}  # fmt: skip


def look(launch_url: str, routes: list[str], never: list[str], out: Path) -> dict:
    """One pass. `launch_url` is the one-time sign-in link (http://host:port/#launch=...). Pictures go to
    out/shots, page texts to out/texts. Returns {"findings": [...], "timings": [...]}."""
    from playwright.sync_api import sync_playwright

    base = launch_url.split("#", 1)[0].rstrip("/")
    shots, texts = out / "shots", out / "texts"
    shots.mkdir(parents=True, exist_ok=True)
    texts.mkdir(parents=True, exist_ok=True)
    findings: list[dict] = []
    timings: list[dict] = []
    with sync_playwright() as pw:
        browser = launch(pw)
        try:
            first = VIEWPORTS[0]
            ctx = browser.new_context(viewport={"width": first["width"], "height": first["height"]})
            page = ctx.new_page()
            cur: dict = {"route": None}
            errs: list[dict] = []

            def note(kind: str, text: str) -> None:
                if cur["route"]:
                    errs.append({"route": cur["route"], "kind": kind, "text": redact(text, base)[:160]})

            page.on("console", lambda m: m.type == "error" and note("console", m.text))
            page.on("pageerror", lambda e: note("pageerror", str(e)))
            page.on(
                "response",
                lambda r: (
                    r.status >= 400
                    and note("http", f"{r.status} {r.request.method} {redact(r.url, base).split('?')[0]}")
                ),
            )
            # one sign-in for the whole pass: the session then lives in this browser context
            with contextlib.suppress(Exception):  # never repeat the address (it holds the sign-in)
                page.goto(launch_url, wait_until="commit", timeout=45000)
            page.wait_for_timeout(3500)
            body = ""
            with contextlib.suppress(Exception):
                body = page.inner_text("body", timeout=5000)
            if "/go/" in page.url or re.search(r"\bSign in\b", body) and _text_len(page) < 200:
                findings.append({"key": "login", "severity": "big", "route": "sign-in", "viewport": first["name"],
                                 "kind": "login", "text": "The sign-in link did not open the dashboard",
                                 "shot": None})  # fmt: skip
                return {"findings": findings, "timings": timings}
            for vp in VIEWPORTS:
                page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                errs.clear()
                for route in routes:
                    cur["route"] = route
                    with contextlib.suppress(Exception):  # timed out: the wait below says so
                        page.goto("about:blank")
                        page.goto(f"{base}/{route}", wait_until="commit", timeout=30000)
                    ms = _wait_main(page, EMPTY_MS)
                    page.wait_for_timeout(1200)
                    shot = shots / f"{vp['name']}-{slug(route)}.png"
                    with contextlib.suppress(Exception):
                        page.screenshot(path=str(shot))
                    timings.append({"route": route, "viewport": vp["name"], "ms": ms})
                    pr = _probe(page, never)
                    if pr and pr.get("text"):
                        (texts / f"{vp['name']}-{slug(route)}.txt").write_text(pr["text"], encoding="utf-8")
                    findings += findings_for(route, vp, ms, pr, str(shot))
                cur["route"] = None
                findings += [error_finding(e, vp, shots) for e in errs]
            ctx.close()
        finally:
            browser.close()
    seen: dict[str, dict] = {}
    for f in findings:  # the same page error at three widths is one finding
        seen.setdefault(f["key"], f)
    return {"findings": list(seen.values()), "timings": timings}
