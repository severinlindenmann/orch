import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper), and the core (orch, orch_ui) is found by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))
sys.path.insert(0, str(HERE.parent / "src"))


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)


def xlsx(rows):
    shared = []
    sheet = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            shared.append(v)
            cells.append(f'<c r="{chr(65 + c)}{r}" t="s"><v>{len(shared) - 1}</v></c>')
        sheet.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}"><sheets><sheet name="Prices" sheetId="1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{ns}">' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>",
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData>{"".join(sheet)}</sheetData></worksheet>',
        )
    return b.getvalue()


def docx(lines):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{x}</w:t></w:r></w:p>" for x in lines)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return b.getvalue()


def write(root: Path, rel: str, data, mtime: float | None = None) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        p.write_text(data, encoding="utf-8")
    else:
        p.write_bytes(data)
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A small café workspace: your folders, noise, a private file, and two tickets with files."""
    root = tmp_path / "Demo"
    (root / ".orch" / "tickets").mkdir(parents=True)
    write(root, "notes.md", "# Team meeting\nWinter menu starts on 1 December.\n", 1_790_000_000)
    write(root, "Finance/summary.md", "# Price check\nMüller invoiced in March\nmore\n", 1_790_000_100)
    write(root, "Finance/budget-2027.xlsx", xlsx([["Area", "Plan"], ["Rent", "54,000"], ["Pumpkin", "12"]]))
    write(root, "Sales/offer.docx", docx(["Offer for Hotel Seeblick", "Breakfast pastries for 60 guests"]))
    write(
        root,
        "Sales/page.html",
        "<html><title>Start</title><script>var x='hidden'</script><p>Opening hours</p></html>",
    )
    write(root, "Marketing/photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    write(root, "Marketing/aws.txt", "AKIAIOSFODNN7EXAMPLE\n")
    write(root, "prod.env", "STRIPE=demo-value\n")
    write(root, ".env", "STRIPE=demo-value\n")  # a system file too: hidden until the switch is on
    write(root, ".claude/settings.json", "{}")
    write(root, "CLAUDE.local.md", "<!-- orch:begin local -->\nUse orch.\n<!-- orch:end local -->\n")
    write(root, "node_modules/pkg/index.js", "module.exports = 'noise'\n")
    write(root, "build/out.txt", "ignored by gitignore\n")
    write(root, "debug.log", "ignored by gitignore\n")
    write(root, "keep.log", "kept by a ! rule\n")
    write(root, ".gitignore", "build/\n*.log\n!keep.log\n")
    write(root, ".orch/run/x.json", "{}")  # orch's own machinery: never listed
    tickets = {
        "t_abc123": {
            "key": "DM-21",
            "title": "Check wholesale prices",
            "status": "active",
            "updated_at": "2026-11-18T10:00:00Z",
            "checklist": [
                {
                    "evidence": [
                        {
                            "type": "file",
                            "ref": ".orch/tickets/t_abc123/evidence/summary.md",
                            "title": "Price check: summary",
                        }
                    ]
                }
            ],
        },
        "t_def456": {
            "key": "DM-6",
            "title": "Price list 2027",
            "status": "done",
            "updated_at": "2020-01-01T10:00:00Z",
        },
        "t_ghi789": {
            "key": "DM-23",
            "title": "Winter menu cards",
            "status": "review",
            "updated_at": "2026-11-18T10:00:00Z",
        },
    }
    for tid, t in tickets.items():
        write(root, f".orch/tickets/{tid}.json", json.dumps({"id": tid, **t}))
    write(
        root,
        ".orch/tickets/t_abc123/artifacts/summary.md",
        "Three of four prices sit in the middle\n",
        1_790_000_200,
    )
    write(root, ".orch/tickets/t_def456/artifacts/price-list-v1.md", "old list\n", 1_790_000_300)
    write(root, ".orch/tickets/t_def456/artifacts/price-list-v2.md", "new list\n", 1_790_000_400)
    write(root, ".orch/tickets/t_ghi789/evidence/card.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    monkeypatch.setenv("ORCH_ROOT", str(root))
    return root.resolve()


@pytest.fixture
def built(ws):
    from orch_files import index

    index.refresh(ws)
    return ws
