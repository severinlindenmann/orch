"""One static HTML report: findings (NOW + PROPOSAL) on top, then lanes with every step, shot, timing."""
from __future__ import annotations

import html
import json
from pathlib import Path

CSS = """
:root{--bg:#fafafa;--fg:#1c1c1e;--mut:#6b6b70;--card:#fff;--line:#e3e3e8;--ok:#1f8a4c;--bad:#c62828;--warn:#b26a00;--acc:#2f5bea}
@media(prefers-color-scheme:dark){:root{--bg:#121214;--fg:#ececf0;--mut:#9a9aa3;--card:#1c1c20;--line:#2e2e35;--ok:#4cc38a;--bad:#ff7b7b;--warn:#f0b04c;--acc:#7da2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}h1{font-size:22px;margin:8px 0}h2{font-size:18px;margin:28px 0 8px}h3{font-size:15px;margin:0}
.sum{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.sum span{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}
.f{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:760px){.f{grid-template-columns:1fr}}
.tag{font-size:12px;border-radius:99px;padding:1px 8px;border:1px solid var(--line);color:var(--mut)}
.blocking{color:var(--bad);border-color:var(--bad)}.functional{color:var(--warn);border-color:var(--warn)}.ux{color:var(--acc);border-color:var(--acc)}
.pass{color:var(--ok)}.fail{color:var(--bad)}.blocked,.skipped,.flaky{color:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}
img.t{height:64px;border:1px solid var(--line);border-radius:4px;margin:2px;vertical-align:middle}img.big{max-width:100%;border:1px solid var(--line);border-radius:6px}
.lab{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}code,pre{font:13px ui-monospace,monospace}
details{margin:4px 0}summary{cursor:pointer}a{color:var(--acc)}
"""


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def img(path: str, big=False) -> str:
    if not path:
        return ""
    return f'<a href="{e(path)}" target="_blank"><img class="{"big" if big else "t"}" loading="lazy" src="{e(path)}" alt="screenshot {e(path)}"></a>'


def render(run: dict, lanes: list[dict], findings: list[dict], census: dict, outdir: Path) -> Path:
    steps = [s for l in lanes for s in l["steps"]]
    cnt = {k: sum(1 for s in steps if s.get("status") == k) for k in ("pass", "fail", "blocked", "skipped", "flaky")}
    sev_order = {"blocking": 0, "functional": 1, "ux": 2}
    findings = sorted(findings, key=lambda f: (sev_order.get(f.get("severity"), 3), f.get("lane", ""), f.get("step", "")))
    h = [f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>orch full e2e {e(run['sha'][:8])}</title><style>{CSS}</style><main>"]
    h.append(f"<h1>orch full e2e: {e(run['mode'])} on {e(run['sha'][:10])}{(' · build ' + e(run['build_label'])) if run.get('build_label') else ''}</h1>")
    h.append(f"<p class=lab>{e(run['started'])} - {e(run['elapsed'])} - run {e(run.get('n'))} (timings are "
             f"{'a gate' if run.get('timing_fail') else 'report-only'})</p><div class=sum>")
    for k, v in cnt.items():
        h.append(f"<span><b class={k}>{v}</b> {k}</span>")
    h.append(f"<span><b>{len(steps)}</b> steps</span><span>control coverage <b>{census.get('percent', 0)}%</b> "
             f"({census.get('clicked', 0)}/{census.get('found', 0)})</span>")
    nb = sum(1 for f in findings if f.get("severity") == "blocking")
    h.append(f"<span><b>{len(findings)}</b> findings ({nb} blocking)</span></div>")
    # findings
    h.append("<h2 id=findings>Findings</h2>")
    if not findings:
        h.append("<p>No findings.</p>")
    for i, f in enumerate(findings, 1):
        sh = "".join(img(s, big=False) for s in f.get("shots", []))
        h.append(f"<div class=card><h3>F{i} {e(f['title'])}{(' (x' + str(f['count']) + ')') if f.get('count', 1) > 1 else ''} <span class='tag {e(f.get('severity'))}'>{e(f.get('severity'))}</span> "
                 f"<span class=tag>{e(f.get('lane'))} {e(f.get('step'))}</span> <span class=tag>{e(f.get('kind'))}</span></h3>"
                 f"<div class=f><div><div class=lab>Now</div>{e(f.get('now'))}<div>{sh}</div></div>"
                 f"<div><div class=lab>Proposal</div>{e(f.get('proposal'))}"
                 f"{'<div class=lab>Heuristic</div>' + e(f['heuristic']) if f.get('heuristic') else ''}</div></div></div>")
    # timings
    probes = [p for l in lanes for p in l.get("probes", {}).values()]
    if probes:
        h.append("<h2>Timings</h2><table><tr><th>Probe<th>Median<th>p95<th>Max<th>Target / limit<th>Samples<th>Result</tr>")
        for p in probes:
            ok = p["median"] is not None and p["median"] <= p["target"] and p["p95"] <= p["hard"]
            h.append(f"<tr><td>{e(p['name'])}<br><span class=lab>{e(p['lane'])} {e(p['id'])} {e(p.get('note'))}</span>"
                     f"<td>{p['median']} {p['unit']}<td>{p['p95']}<td>{p['max']}<td>{p['target']} / {p['hard']}"
                     f"<td>{len(p['samples'])}<td class={'pass' if ok else 'fail'}>{'within target' if ok else 'over'}</tr>")
        h.append("</table>")
    # lanes
    for l in lanes:
        h.append(f"<h2 id=lane-{e(l['lane'])}>Lane {e(l['lane'])}: {e(l.get('title'))}</h2>")
        for n in l.get("notes", []):
            h.append(f"<p class=lab>{e(n)}</p>")
        c = l.get("coverage")
        if c:
            h.append(f"<p>Control coverage {c.get('percent')}% ({c.get('clicked')}/{c.get('found')})</p>")
        h.append("<table><tr><th>Step<th>What<th>Result<th>Time<th>Shots</tr>")
        for s in l["steps"]:
            shots = "".join(img(f"{l['dir']}/{x['file']}") for x in s.get("shots", []))
            extra = ""
            if s.get("error"):
                extra += f"<div class=fail>{e(s['error'])}</div>"
            if s.get("note"):
                extra += f"<div class=lab>{e(s['note'])}</div>"
            acts = s.get("actions") or []
            if acts:
                extra += "<details><summary>actions</summary>" + "".join(
                    f"<div><code>{e(a.get('do'))} {e(a.get('sel') or a.get('path') or a.get('text') or '')}</code> {a.get('ms', '')} ms "
                    f"{('<b class=fail>' + e(a.get('error')) + '</b>') if a.get('error') else ''}</div>" for a in acts) + "</details>"
            h.append(f"<tr><td>{e(s['id'])}<td>{e(s['name'])}<br><span class=lab>{e(s.get('expect'))}</span>{extra}"
                     f"<td class={e(s['status'])}>{e(s['status'])}<td>{s.get('ms', 0)} ms<td>{shots}</tr>")
        h.append("</table>")
    if run.get("manual"):
        h.append("<h2>Manual (not automated)</h2><ul>" + "".join(f"<li>{e(m)}</li>" for m in run["manual"]) + "</ul>")
    h.append("</main></html>")
    path = outdir / "index.html"
    path.write_text("".join(h))
    (outdir / "summary.json").write_text(json.dumps({"run": run, "counts": cnt, "coverage": census,
                                                     "findings": findings, "probes": {p["id"]: p for p in probes}}, indent=1))
    return path
