"""The Documentation page's content (contracts/docs-pages.md, orch/docs.py): every shipped docs file is valid,
the pages come together in the right groups, and a bad docs file refuses its add-on."""

import json
from pathlib import Path

import jsonschema
import pytest

from orch import addons, docs

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO / "contracts" / "docs-pages.schema.json").read_text(encoding="utf-8"))
MANIFESTS = sorted((REPO / "workspace" / "src" / "orch" / "builtin").glob("*/orch-addon.toml")) + sorted(
    (REPO / "workspace-addons").glob("*/src/*/orch-addon.toml")
)


def _rows(off=("sync",)):
    rows = []
    for f in MANIFESTS:
        m = addons.parse_manifest(f, core="builtin" in f.parts)
        rows.append(
            {
                "name": m["name"],
                "active": m["name"] not in off,
                "running": False,
                "docs_pages": m["docs_pages"],
            }
        )
    return rows


def test_every_docs_file_follows_the_schema_and_the_checker():
    files = [docs.core_file()] + [f.parent / "docs.json" for f in MANIFESTS]
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        jsonschema.validate(data, SCHEMA)
        assert docs.check(data, f.name)


def test_every_shipped_addon_brings_its_own_pages():
    for f in MANIFESTS:
        m = addons.parse_manifest(f, core="builtin" in f.parts)
        assert m.get("docs") == "docs.json", m["name"]
        assert m["docs_pages"], m["name"]
        for p in m["docs_pages"]:
            assert p.get("tech", {}).get("cmds"), f"{m['name']}: page {p['id']} names the commands behind it"


def test_collect_orders_groups_marks_off_and_keeps_links_inside():
    out = docs.collect(_rows())
    pages = out["pages"]
    assert [g["id"] for g in out["groups"]] == ["orch", "builtin", "addon"]
    groups = [p["group"] for p in pages]
    assert groups == sorted(groups, key=["orch", "builtin", "addon"].index), (
        "orch first, then relay and publish, then add-ons"
    )
    assert [p["addon"] for p in pages if p["group"] == "builtin"][0] == "relay"
    ids = [p["id"] for p in pages]
    assert len(ids) == len(set(ids)) == 28
    assert next(p for p in pages if p["id"] == "sync")["on"] is False
    assert all(r in ids for p in pages for r in p["related"])
    assert set(out["actors"]) == {"you", "orch", "helper", "other", "server"}


def test_an_addon_never_replaces_a_page_that_is_already_there():
    rows = _rows() + [
        {
            "name": "zz-copy",
            "active": True,
            "running": False,
            "docs_pages": [
                {
                    "id": "new-ticket",
                    "icon": "plus",
                    "title": "Mine",
                    "one": "Mine.",
                    "steps": [{"who": "you", "text": "x"}],
                }
            ],
        }
    ]
    pages = docs.collect(rows)["pages"]
    assert [p["title"] for p in pages if p["id"] == "new-ticket"] == ["After you make a ticket"]


@pytest.mark.parametrize(
    "page, why",
    [
        (
            {"id": "x1", "icon": "plus", "title": "T", "one": "O", "steps": [{"who": "robot", "text": "x"}]},
            "who is",
        ),
        (
            {"id": "x1", "icon": "nope", "title": "T", "one": "O", "steps": [{"who": "you", "text": "x"}]},
            "icon",
        ),
        (
            {"id": "x1", "icon": "plus", "title": "<b>", "one": "O", "steps": [{"who": "you", "text": "x"}]},
            "title",
        ),
        (
            {
                "id": "x1",
                "icon": "plus",
                "title": "T",
                "one": "O",
                "steps": [{"who": "you", "text": "x"}],
                "tech": {"live": ["weather"]},
            },
            "live",
        ),
        (
            {
                "id": "x1",
                "icon": "plus",
                "title": "T",
                "one": "O",
                "kind": "states",
                "states": [{"id": "a1", "label": "A"}, {"id": "b1", "label": "B"}],
                "moves": [{"from": "a1", "to": "zz", "by": "you", "text": "go"}],
            },
            "between two",
        ),
        (
            {"id": "x1", "icon": [], "title": "T", "one": "O", "steps": [{"who": "you", "text": "x"}]},
            "wrong kind",
        ),
        (
            {
                "id": "x1",
                "icon": "plus",
                "title": "T",
                "one": "O",
                "steps": [{"who": "you", "text": "x"}],
                "tech": {"live": [{}]},
            },
            "wrong kind",
        ),
    ],
)
def test_a_bad_page_is_refused_with_what_is_off(page, why):
    with pytest.raises(docs.DocsError, match=why):
        docs.check({"schema": docs.SCHEMA, "pages": [page]})


def test_a_manifest_with_a_bad_docs_file_refuses_the_addon(tmp_path):
    pkg = tmp_path / "orch_demo"
    (pkg / "skill").mkdir(parents=True)
    (pkg / "skill" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    (pkg / "skill" / "AGENTS-block.md").write_text("demo\n", encoding="utf-8")
    (pkg / "orch-addon.toml").write_text(
        'schema = "orch.addon/1"\norch_api = 1\nname = "demo"\nversion = "0.1.0"\ndescription = "Demo."\n'
        'run = "orch_demo"\nskill = "skill"\ndocs = "docs.json"\n',
        encoding="utf-8",
    )
    (pkg / "docs.json").write_text(json.dumps({"schema": "orch.docs/1", "pages": []}), encoding="utf-8")
    with pytest.raises(addons.Refused, match="docs file is not valid"):
        addons.parse_manifest(pkg / "orch-addon.toml")
    (pkg / "docs.json").write_text(
        json.dumps(
            {
                "schema": "orch.docs/1",
                "pages": [
                    {
                        "id": "demo",
                        "icon": "box",
                        "title": "Demo",
                        "one": "It shows.",
                        "steps": [{"who": "orch", "text": "Shows it"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert addons.parse_manifest(pkg / "orch-addon.toml")["docs_pages"][0]["id"] == "demo"


def test_the_gallery_and_mockup_sample_is_current():
    """samples/docs-sample.js (gallery + mockup) is generated from the docs files: run
    scripts/gen_docs_sample.py."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_docs_sample", REPO / "scripts" / "gen_docs_sample.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.OUT.read_text(encoding="utf-8") == gen.render(), "run: python3 scripts/gen_docs_sample.py"


def test_the_schema_asks_for_the_content_of_each_kind():
    bare = {"id": "x1", "icon": "plus", "title": "T", "one": "O"}
    for page in (bare, {**bare, "kind": "states"}, {**bare, "kind": "compare"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"schema": "orch.docs/1", "pages": [page]}, SCHEMA)
