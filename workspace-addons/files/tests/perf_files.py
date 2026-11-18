"""The plan's speed numbers on a generated workspace (not part of the normal test run: it writes 100,000 files).

    python tests/perf_files.py <empty folder> [--files 100000]

Prints one JSON line: first build, re-check of the unchanged workspace (must read no file), name search and
content search p50/p95 over 200 queries each, and the index size against the text it holds. test_speed.py runs
the same with ORCH_FILES_PERF=1 and checks the targets: names p95 < 50 ms, content p95 < 150 ms, re-check < 2 s.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "workspace" / "src"))

from orch_files import index

WORDS = ["invoice", "order", "offer", "price", "list", "budget", "menu", "winter", "summer", "spring", "autumn", "coffee", "milk", "croissant", "pastry", "delivery", "customer", "supplier", "hotel", "bakery", "office", "breakfast", "lunch", "dinner", "terrace", "photo", "newsletter", "catalogue", "allergen", "gluten", "nuts", "oat", "cookie", "tart", "rhubarb", "apple", "strudel", "chocolate", "orange", "cinnamon", "chai", "latte", "espresso", "roast", "beans", "kilo", "tray", "box", "guests", "weekly", "daily", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "report", "meeting", "notes", "plan", "check", "summary", "draft", "version", "final", "review", "website", "start", "page", "hours", "opening", "closed", "holiday", "account", "tax", "receipt", "payment", "refund", "credit", "note", "currency", "franc", "euro", "dollar", "staff", "wages", "rent", "marketing"]
NAMES = [
    "Müller",
    "Rossi",
    "Keller",
    "Bianchi",
    "Meier",
    "Huber",
    "Frei",
    "Graf",
    "Brunner",
    "Zürich",
    "Genève",
]
KINDS = [".md"] * 5 + [".txt"] * 3 + [".csv"] * 2 + [".py", ".json", ".png", ".pdf"]


def make(root: Path, n: int, seed: int = 7) -> int:
    rnd = random.Random(seed)
    text_bytes = 0
    (root / ".orch" / "tickets").mkdir(parents=True, exist_ok=True)
    per = 100
    for i in range(n):
        d = root / f"area-{i // (per * 20):02d}" / f"folder-{(i // per) % 20:02d}-{i // per}"
        if i % per == 0:
            d.mkdir(parents=True, exist_ok=True)
        ext = rnd.choice(KINDS)
        name = "-".join(rnd.sample(WORDS, 2)) + f"-{i}{ext}"
        if ext in (".png", ".pdf"):
            (d / name).write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(rnd.getrandbits(8) for _ in range(256)))
            continue
        lines = []
        for _ in range(rnd.randint(4, 30)):
            ws = rnd.choices(WORDS, k=rnd.randint(6, 14))
            if rnd.random() < 0.05:
                ws.insert(rnd.randint(0, len(ws)), rnd.choice(NAMES))
            lines.append(" ".join(ws))
        body = "\n".join(lines) + "\n"
        text_bytes += len(body.encode())
        (d / name).write_text(body, encoding="utf-8")
    return text_bytes


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 1)


def measure(root: Path, text_bytes: int) -> dict:
    t0 = time.monotonic()
    first = index.refresh(root)
    build = time.monotonic() - t0
    again = index.refresh(root)
    rnd = random.Random(3)
    name_q = [rnd.choice(WORDS)[: rnd.randint(3, 7)] for _ in range(200)]
    text_q = [
        rnd.choice([rnd.choice(WORDS), rnd.choice(NAMES).lower(), " ".join(rnd.sample(WORDS, 2))])
        for _ in range(200)
    ]
    names, texts = [], []
    for q in name_q:
        t = time.perf_counter()
        index.search(root, q, 60, names_only=True)
        names.append((time.perf_counter() - t) * 1000)
    for q in text_q:
        t = time.perf_counter()
        index.search(root, q, 60)
        texts.append((time.perf_counter() - t) * 1000)
    size = index.size_on_disk(root)
    return {
        "files": first.total,
        "first_build_s": round(build, 1),
        "recheck_s": again.seconds,
        "recheck_read": again.read,
        "recheck_changed": again.changed,
        "names_p50_ms": pct(names, 0.5),
        "names_p95_ms": pct(names, 0.95),
        "content_p50_ms": pct(texts, 0.5),
        "content_p95_ms": pct(texts, 0.95),
        "index_mb": round(size / 1048576, 1),
        "text_mb": round(text_bytes / 1048576, 1),
        "index_vs_text": round(size / max(1, text_bytes), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--files", type=int, default=100_000)
    a = ap.parse_args()
    root = Path(a.folder)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        print("Give an empty folder.", file=sys.stderr)
        return 2
    t = time.monotonic()
    tb = make(root, a.files)
    out = {"generate_s": round(time.monotonic() - t, 1), **measure(root, tb)}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    os.nice(0)
    sys.exit(main())
