"""Static single-file snapshot: the same pages with the data embedded. No inbox (private messages stay local)."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .data import load_state
from .server import web_file
from .views import ViewPuller


def _inline_json(obj) -> str:
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_snapshot(root: Path, with_addons: bool = False, orch_bin: str | None = None) -> str:
    """Return the snapshot as one HTML string (css, js, logo and data inline)."""
    orch_bin = orch_bin or os.environ.get("ORCH_BIN") or None
    state = load_state(root, include_inbox=False, orch_bin=orch_bin, with_addons=with_addons)
    if with_addons:  # the user asked: add-on tabs go along, each with one pulled view
        puller = ViewPuller(root, orch_bin)
        state["views"] = {a["name"]: puller.pull(a["name"]) for a in state["addons"] if a["dashboard"]}
    html = web_file("index.html").decode()
    css = web_file("tokens.css").decode() + "\n" + web_file("style.css").decode()
    js = web_file("blocks.js").decode() + "\n" + web_file("app.js").decode()
    logo = base64.b64encode(web_file("logo.svg")).decode()
    html = html.replace('src="logo.svg"', f'src="data:image/svg+xml;base64,{logo}"')
    icon = base64.b64encode(web_file("favicon.svg")).decode()
    html = html.replace('href="favicon.svg"', f'href="data:image/svg+xml;base64,{icon}"')
    html = html.replace('<link rel="apple-touch-icon" href="apple-touch-icon.png">\n', "")
    html = html.replace('<link rel="stylesheet" href="tokens.css">', "")
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>{css}</style>")
    html = html.replace('<script src="blocks.js"></script>\n<script src="app.js"></script>',
                        f"<script>window.ORCH_SNAPSHOT={_inline_json(state)};</script><script>{js}</script>")
    return html


def write_snapshot(root: Path, out: Path, with_addons: bool = False) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_snapshot(root, with_addons), encoding="utf-8")
    return out


def _app_name(root: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-")[:30].strip("-")
    return f"dashboard-{slug}" if slug else "dashboard"


def write_app(root: Path, folder: Path, with_addons: bool = False) -> Path:
    """Write a deployable static app folder (index.html + app.toml, private) per contracts/app.toml.md."""
    write_snapshot(root, folder / "index.html", with_addons)
    (folder / "app.toml").write_text(
        f'name   = "{_app_name(root)}"\nabout  = "Read-only dashboard snapshot"\nstack  = "static"\n'
        'store  = "none"\npublic = false\n',
        encoding="utf-8",
    )
    return folder


def publish_snapshot(root: Path, run=subprocess.run, with_addons: bool = False) -> int:
    """Build the static app in a temp folder and call `orch publish app <folder> --private`.
    The orch CLI prints the private link."""
    with tempfile.TemporaryDirectory(prefix="orch-dash-") as d:
        write_app(root, Path(d), with_addons)
        try:
            return run(["orch", "publish", "app", d, "--private"]).returncode
        except FileNotFoundError:
            print("The orch command was not found. Install orch first.", file=sys.stderr)
            return 127
