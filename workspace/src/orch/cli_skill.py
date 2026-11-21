"""`orch skill check | list | show`: the skill headers of this workspace, read-only (skillmeta.py).
`orch skill review-due`: a ticket per skill whose review-by date has passed (skillreview.py)."""

from __future__ import annotations

import json
from pathlib import Path

from orch import skillmeta
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    s = sub.add_parser("skill", help="the skills of this workspace and their headers").add_subparsers(
        dest="sub", required=True
    )
    c = s.add_parser("check", parents=[common], help="check skill headers; exit 2 when one is broken")
    c.add_argument("names", nargs="*", help="skills of this workspace (default: all)")
    c.add_argument("--path", action="append", default=[], help="a skill folder to check instead (repeatable)")
    s.add_parser("list", parents=[common], help="every skill here with its header")
    x = s.add_parser("show", parents=[common], help="one skill: its header and what the check says")
    x.add_argument("name")
    r = s.add_parser(
        "review-due",
        parents=[common],
        help="a ticket for each skill whose review-by date has passed (no AI; the automation runs it hourly)",
    )
    r.add_argument("--dry-run", action="store_true", help="only say which tickets it would open")


def _entries_for_paths(paths: list[str]) -> list[dict]:
    out = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.name == "SKILL.md":
            p = p.parent
        if not p.is_dir():
            raise Refused(f"{raw} is not a skill folder. Give the folder that holds SKILL.md.")
        out.append(skillmeta._entry(p.name, p, "path"))
    return out


def _text_findings(findings: list[dict], count: int) -> str:
    if not findings:
        return f"All {count} skills pass."
    lines = [
        f"{f['skill']}: {'problem' if f['level'] == 'error' else 'note'}: {f['message']}" for f in findings
    ]
    errs = sum(f["level"] == "error" for f in findings)
    lines.append(f"{count} skills checked: {errs} problems, {len(findings) - errs} notes.")
    return "\n".join(lines)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "skill":
        return False
    if args.sub == "check":
        if args.path:
            entries = _entries_for_paths(args.path)
        else:
            entries = skillmeta.list_skills(root)
            if args.names:
                known = {e["name"] for e in entries}
                for n in args.names:
                    if n not in known:
                        raise Refused(f"There is no skill {n!r} here. See them with: orch skill list")
                entries = [e for e in entries if e["name"] in args.names]
        findings = skillmeta.check_all(entries, root)
        ok = not any(f["level"] == "error" for f in findings)
        res = {"ok": ok, "checked": [e["name"] for e in entries], "findings": findings}
        print(
            json.dumps(res, indent=2, ensure_ascii=False)
            if args.json
            else _text_findings(findings, len(entries))
        )
        if not ok and args.json:
            raise SystemExit(2)  # one JSON answer; "ok": false says it
        if not ok:
            bad = sorted({f["skill"] for f in findings if f["level"] == "error"})
            raise Refused(f"Skill headers to fix: {', '.join(bad)}. The lines above say what to change.")
    elif args.sub == "list":
        entries = skillmeta.list_skills(root)
        if args.json:
            print(json.dumps(entries, indent=2, ensure_ascii=False))
        else:
            for e in entries:
                meta = (e["header"] or {}).get("metadata") or {}
                extra = ", ".join(
                    f"{k}: {v}" for k, v in meta.items() if k in ("status", "owner", "platforms")
                )
                state = f"cannot read: {e['error']}" if e["error"] else extra
                print(f"{e['name']}  ({e['source']}){'  ' + state if state else ''}")
            if not entries:
                print("No skills here.")
    elif args.sub == "show":
        e = skillmeta.find(root, args.name)
        res = {**e, "findings": skillmeta.check_all([e], root)}
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            h = e["header"] or {}
            lines = [f"{e['name']}  ({e['source']})", e["path"]]
            if e["error"]:
                lines.append(f"Cannot read the header: {e['error']}")
            else:
                lines.append(h.get("description", ""))
                lines += [f"  {k}: {v}" for k, v in h.items() if k not in ("name", "description", "metadata")]
                lines += [f"  metadata.{k}: {v}" for k, v in (h.get("metadata") or {}).items()]
            lines.append(_text_findings(res["findings"], 1))
            print("\n".join(lines))
    elif args.sub == "review-due":
        from orch import skillreview

        res = skillreview.review_due(root, dry_run=args.dry_run)
        print(skillreview.dumps(res) if args.json else skillreview.text(res))
    return True
