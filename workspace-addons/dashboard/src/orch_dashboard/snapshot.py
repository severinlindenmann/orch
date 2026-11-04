"""Static single-file snapshot: the same pages with the data embedded. No inbox (private messages stay local)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .data import load_state
from .server import web_file


def _inline_json(obj) -> str:
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_snapshot(root: Path) -> str:
    """Return the snapshot as one HTML string (css, js, logo and data inline)."""
    state = load_state(root, include_inbox=False)
    html = web_file("index.html").decode()
    css = web_file("tokens.css").decode() + "\n" + web_file("style.css").decode()
    js = web_file("app.js").decode()
    html = html.replace('<link rel="stylesheet" href="tokens.css">', "")
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>{css}</style>")
    html = html.replace('<script src="app.js"></script>',
                        f"<script>window.ORCH_SNAPSHOT={_inline_json(state)};</script><script>{js}</script>")
    return html


def write_snapshot(root: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_snapshot(root), encoding="utf-8")
    return out


def _app_name(root: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-")[:30].strip("-")
    return f"dashboard-{slug}" if slug else "dashboard"


def write_app(root: Path, folder: Path) -> Path:
    """Write a deployable static app folder (index.html + app.toml, private) per contracts/app.toml.md."""
    write_snapshot(root, folder / "index.html")
    (folder / "app.toml").write_text(
        f'name   = "{_app_name(root)}"\nabout  = "Read-only dashboard snapshot"\nstack  = "static"\n'
        'store  = "none"\npublic = false\n',
        encoding="utf-8",
    )
    return folder


def publish_snapshot(root: Path, run=subprocess.run) -> int:
    """Build the static app in a temp folder and call `orch publish app <folder> --private`.
    The orch CLI prints the private link."""
    with tempfile.TemporaryDirectory(prefix="orch-dash-") as d:
        write_app(root, Path(d))
        try:
            return run(["orch", "publish", "app", d, "--private"]).returncode
        except FileNotFoundError:
            print("The orch command was not found. Install orch first.", file=sys.stderr)
            return 127
