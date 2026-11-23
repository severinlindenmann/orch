import json
import tomllib
from pathlib import Path

from orch_files.cli import main

SRC = Path(__file__).resolve().parents[1] / "src" / "orch_files"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_search_json(ws, capsys):
    code, out, _ = run(capsys, "--dir", str(ws), "search", "muller", "--json")
    assert code == 0
    res = json.loads(out)
    assert (
        res["items"][0]["path"] == "Finance/summary.md"
        and res["items"][0]["line"] == "Müller invoiced in March"
    )
    assert (ws / ".orch" / "cache" / "files" / "index.db").exists()


def test_search_words_and_plain_output(ws, capsys):
    code, out, _ = run(capsys, "--dir", str(ws), "search", "price", "check")
    assert code == 0 and "Finance/summary.md" in out and "found among" in out
    code, out, _ = run(capsys, "--dir", str(ws), "search", "birthday", "cake", "--no-refresh")
    assert code == 0 and "Nothing found" in out


def test_index_command(ws, capsys):
    code, out, _ = run(capsys, "--dir", str(ws), "index", "--json")
    data = json.loads(out)
    assert (
        code == 0
        and data["ready"]
        and data["total"] >= 10
        and data["unread"] == 0
        and data["index_bytes"] > 0
    )


def test_no_workspace(tmp_path, capsys):
    code, _, err = run(capsys, "--dir", str(tmp_path), "search", "x")
    assert code == 2 and "No orch workspace" in err


def test_manifest_and_skill():
    m = tomllib.loads((SRC / "orch-addon.toml").read_text())
    assert m["name"] == "files" and m["run"] == "orch_files" and m["background"] is True
    assert m["dashboard"]["stage"] == "preview" and m["dashboard"]["icon"] == "folder"
    assert m["page"]["path"] == "/"
    assert not m.get("recommended")  # opt-in: never turned on by orch init --recommended
    assert (SRC / m["skill"] / "SKILL.md").exists() and (SRC / m["agents_block"]).exists()
    assert ".orch/cache/files/" in m["gitignore"]
    block = (SRC / m["agents_block"]).read_text()
    assert block.startswith("## orch-files") and "orch files search" in block


def test_core_accepts_the_manifest():
    from orch import addons

    m = addons.parse_manifest(SRC / "orch-addon.toml")
    assert m["dashboard"]["stage"] == "preview" and m["name"] == "files"
