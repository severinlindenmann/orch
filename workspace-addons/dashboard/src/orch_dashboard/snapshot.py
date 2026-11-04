"""Static single-file snapshot: the same pages with the data embedded. No inbox (private messages stay local)."""
from __future__ import annotations

import json
import subprocess
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


def publish_snapshot(root: Path, run=subprocess.run) -> int:
    """Write the snapshot into a temp folder and call `orch publish app <folder>` (private, static)."""
    with tempfile.TemporaryDirectory(prefix="orch-dash-") as d:
        write_snapshot(root, Path(d) / "index.html")
        return run(["orch", "publish", "app", d]).returncode
