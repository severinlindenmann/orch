"""`orch publish new`: copy an app template (static, python, node) into a folder (contracts/app.toml.md)."""

from __future__ import annotations

import shutil
from pathlib import Path

from orch.errors import Refused
from orch.publish import NAME_RE

HERE = Path(__file__).resolve().parent / "templates"
STACKS = ("static", "python", "node")
STORES = ("none", "json", "markdown", "sqlite")
SKIP = {"__pycache__", "node_modules", ".DS_Store"}
ABOUT = "A small app made with orch publish"


def create(stack: str, store: str, folder: Path, name: str | None = None) -> dict:
    """Copy the template into `folder` (must not exist or be empty). Returns {name, stack, store, folder}."""
    if stack not in STACKS:
        raise Refused("Stack must be static, python or node.")
    if store not in STORES:
        raise Refused("Store must be none, json, markdown or sqlite.")
    if stack == "static" and store not in ("none", "markdown"):
        raise Refused("A static app has no server, so its store is none or markdown.")
    name = name or folder.resolve().name
    if not NAME_RE.match(name):
        raise Refused("The folder name becomes the app name: 2 to 40 lowercase letters, digits or dashes.")
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise Refused(f"{folder} is not empty.")
    subs = {"{{name}}": name, "{{slug}}": name, "{{about}}": ABOUT, "{{store}}": store}

    def put(src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(src, dst)
            return
        for k, v in subs.items():
            text = text.replace(k, v)
        dst.write_text(text, encoding="utf-8")

    for src in sorted((HERE / stack).rglob("*")):
        rel = src.relative_to(HERE / stack)
        if src.is_file() and not SKIP & set(rel.parts):
            put(src, folder / rel)
    if stack == "static" and store == "markdown":
        put(HERE / "static-markdown" / "index.html", folder / "index.html")
    if store == "markdown":
        put(HERE / "content" / "welcome.md", folder / "content" / "welcome.md")
    if stack != "static":
        ext = "py" if stack == "python" else "js"
        put(HERE / "stores" / f"{stack}-{store}.{ext}", folder / f"store.{ext}")
    return {"name": name, "stack": stack, "store": store, "folder": str(folder)}
