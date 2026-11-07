"""Turn lane results into findings, each NOW (what happens, with shot) + PROPOSAL (what it should be)."""
from __future__ import annotations

AXE_FIX = {
    "color-contrast": "Raise the text/background contrast to at least 4.5:1 (3:1 for large text) with the design tokens.",
    "label": "Give the field a visible label or an aria-label.",
    "button-name": "Give the icon button a text label or aria-label that says what it does.",
    "link-name": "Give the link readable text or an aria-label.",
    "image-alt": "Add alt text (empty alt for decoration).",
}
LINT_FIX = {
    "vpn-product": 'Say "private network (VPN)" and never the product name.',
    "never-word": "Use the word from docs/wording.md (Ticket, Task, Proof, Suggested, Repeats, Needs you).",
    "jargon": "Replace the technical word with a plain one a non-technical person knows.",
    "typed-word": "Make it one plain click; owner rule: no typed words.",
}


def shot_of(step: dict, n: int = 0) -> list[str]:
    s = step.get("shots") or []
    return [s[n]["file"]] if len(s) > n else []


def from_lane(res: dict, lane_dir: str, timing_fail: bool) -> list[dict]:
    out: list[dict] = list(res.get("findings") or [])
    lane = res["lane"]

    def add(kind, severity, title, now, proposal, st, shots=None):
        out.append({"lane": lane, "kind": kind, "severity": severity, "title": title, "now": now, "proposal": proposal,
                    "step": st.get("id", ""), "shots": [f"{lane_dir}/{p}" for p in (shots if shots is not None else shot_of(st))]})

    for st in res.get("steps", []):
        sid, name = st.get("id"), st.get("name", "")
        if st.get("status") == "fail":
            sev = "blocking" if lane in ("B", "W", "S") else "functional"
            add("step-failed", sev, f"{sid} {name}: step failed",
                f"The step did not pass: {st.get('error') or 'see actions'}.",
                f"Expected: {st.get('expect') or name}. Fix the cause; the step is the repro (`--lanes {lane}`).", st)
        if st.get("status") == "blocked":
            add("step-blocked", "functional", f"{sid} {name}: blocked", f"Could not run: {st.get('error')}",
                "Unblock the earlier step or the environment, then rerun.", st)
        for c in (st.get("console") or [])[:3]:
            add("console", "functional", f"{sid}: console error", f"The page logged an error: {str(c)[:200]}",
                "No console errors on a normal use of this page.", st)
        for h in (st.get("http_errors") or [])[:3]:
            add("http", "functional", f"{sid}: request failed",
                f"{h.get('method')} {h.get('url')} answered {h.get('status')}.", "The page should not make requests that fail.", st)
        for a in (st.get("axe") or [])[:5]:
            add("axe", "ux", f"{sid}: accessibility, {a.get('id')}",
                f"{a.get('help')} ({a.get('impact')}, {a.get('count', 1)} elements, first: {a.get('selector', '')}).",
                AXE_FIX.get(a.get("id"), "Fix as axe describes."), st)
        for l in (st.get("lint") or [])[:4]:
            add("wording", "ux", f"{sid}: wording, {l.get('rule')}", f"The screen says \"{l.get('text')}\" ({l.get('where', '')}).",
                LINT_FIX.get(l.get("rule"), "Use the word from docs/wording.md."), st)
        for s in st.get("shots") or []:
            if s.get("hscroll"):
                add("layout", "ux", f"{sid}: sideways scroll at {s.get('vp')} px",
                    f"At {s.get('vp')} px wide the page scrolls sideways.", "Nothing wider than the screen; wrap or stack at this width.",
                    st, [s["file"]])
        for u in (st.get("unnamed_controls") or [])[:3]:
            add("a11y", "ux", f"{sid}: control without a name", f"A control has no accessible name: {u}.",
                "Give every icon button a label that says what it does.", st)
    cov = res.get("coverage")
    if cov and cov.get("found") and cov.get("percent", 100) < 100:
        un = cov.get("uncovered", [])
        out.append({"lane": lane, "kind": "coverage", "severity": "functional", "step": "", "shots": [],
                    "title": f"Control coverage {round(cov['percent'])}% ({cov['clicked']}/{cov['found']})",
                    "now": f"{len(un)} controls were never clicked, e.g. {', '.join(un[:6])}.",
                    "proposal": "Add a step for each control (data: lanes/*.json) or put it on the destructive allow-list with a reason."})
    for p in (res.get("probes") or {}).values():
        if p.get("median") is None:
            continue
        over_t, over_h = p["median"] > p["target"], p["p95"] > p["hard"]
        if over_t or over_h:
            sev = "functional" if (over_h and timing_fail) else "ux"
            out.append({"lane": lane, "kind": "timing", "severity": sev, "step": p["id"], "shots": [],
                        "title": f"Slow: {p['name']}",
                        "now": f"Median {p['median']} {p['unit']} (target {p['target']}), p95 {p['p95']} (limit {p['hard']}), "
                               f"{len(p['samples'])} samples." + ("" if timing_fail else " Report-only for the first 2 runs."),
                        "proposal": "Show an immediate 'Starting...' state at the click, poll every 1 s while a run is active "
                                    "(or use server-sent events), and show a 'last updated' hint when data is stale."})
    return out
