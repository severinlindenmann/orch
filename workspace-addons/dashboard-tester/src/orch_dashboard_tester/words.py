"""The words orch must never put on screen: the "Never use in the UI" column of docs/wording.md (its one source).

A normal install has no docs folder, so the list ships as never_words.json next to this file. A test checks that
the shipped file matches docs/wording.md; regenerate it with `python -m orch_dashboard_tester.words <wording.md>`.
Entries that only make sense inside a sentence (quotes, brackets, code) are left out.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SHIPPED = Path(__file__).with_name("never_words.json")


def parse(text: str) -> list[str]:
    words: list[str] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 6 or not cells[1] or set(cells[1]) <= {"-"} or cells[1] == "Thing":
            continue
        for w in (x.strip() for x in cells[-2].split(",")):
            if w and w != "-" and not any(ch in w for ch in "()\"'<>`") and w not in words:
                words.append(w)
    return words


def load() -> list[str]:
    try:
        data = json.loads(SHIPPED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [w for w in data if isinstance(w, str)] if isinstance(data, list) else []


def render(text: str) -> str:
    return json.dumps(parse(text), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":  # pragma: no cover - a maintainer's tool
    SHIPPED.write_text(render(Path(sys.argv[1]).read_text(encoding="utf-8")), encoding="utf-8")
    print("ok", SHIPPED)
