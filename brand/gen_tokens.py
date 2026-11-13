"""Generate brand/tokens.css (and the kit copy) from brand/tokens.json, the one source of design tokens.

    python brand/gen_tokens.py           write the css files
    python brand/gen_tokens.py --check   exit 1 when a css file is out of sync
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "tokens.json"
TARGETS = [HERE / "tokens.css", HERE.parent / "workspace" / "src" / "orch_ui" / "static" / "tokens.css"]


def render(t: dict) -> str:
    if t.get("schema") != "orch.tokens/1":
        raise SystemExit("tokens.json: schema must be orch.tokens/1")
    out = [
        "/* GENERATED from brand/tokens.json by brand/gen_tokens.py. Do not edit by hand. */",
        ":root {",
        "  color-scheme: dark;",
    ]
    out += [f"  --{k}: {v};" for k, v in t["color"].items()]
    out += [f"  --{k}: {v};" for k, v in t.get("font", {}).items()]
    out += [f"  --{k}: {v}px;" for k, v in t.get("size", {}).items()]
    out += [f"  --{k}: {v};" for k, v in t.get("layout", {}).items()]
    for i, (k, v) in enumerate(t["type"].items(), 1):
        out.append(f"  --fs-{i}: {v}px; /* {k} */")
    out += [f"  --s{i}: {v}px;" for i, v in enumerate(t["space"], 1)]
    out.append(f"  --r1: {t['radius']['sm']}px;")
    out.append(f"  --r2: {t['radius']['md']}px;")
    out.append(f"  --radius: {t['radius']['sm']}px;")
    out.append(f"  --radius-card: {t['radius']['md']}px;")
    out.append(f"  --h: {t['button']['height']}px;")
    out.append(f"  --touch: {t['button']['touch']}px;")
    out += [f"  --{k}: {v};" for k, v in t["motion"].items()]
    out += [f"  --{k}: {v};" for k, v in t["code"].items()]
    out.append("}")
    for k in t["code"]:
        out.append(f".{k} {{ color: var(--{k}); }}")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    css = render(json.loads(SOURCE.read_text()))
    if "--check" in argv:
        bad = [p for p in TARGETS if not p.exists() or p.read_text() != css]
        for p in bad:
            print(f"out of sync: {p.relative_to(HERE.parent)}", file=sys.stderr)
        if not bad:
            print("tokens.css: in sync")
        return 1 if bad else 0
    for p in TARGETS:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(css)
        print(f"wrote {p.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
