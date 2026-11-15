"""Live text of an add-on (AGENTS-extra.md) is appended under that add-on's block, generically."""

import re
from pathlib import Path

from orch import harness


def _ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    return root


def _extra(root: Path, name: str, text: str | bytes) -> Path:
    d = root / ".orch" / "addons" / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "AGENTS-extra.md"
    f.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return f


def test_extra_follows_its_own_block_and_rebuild_writes_it(tmp_path):
    root = _ws(tmp_path)
    harness.set_block(root, "alpha", "## Alpha\nDo alpha.", addon=True)
    harness.set_block(root, "beta", "## Beta\nDo beta.", addon=True)
    _extra(root, "alpha", "Notes:\n- one\n- two\n")
    harness.rebuild(root)
    text = (root / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    assert text.index("Do alpha.") < text.index("- one") < text.index("- two") < text.index("## Beta")
    assert "- one" in harness.start_text(root)


def test_extra_of_an_add_without_block_is_ignored(tmp_path):
    root = _ws(tmp_path)
    harness.set_block(root, "alpha", "## Alpha\nA.", addon=True)
    _extra(root, "gone", "- secret plan\n")
    harness.rebuild(root)
    assert "secret plan" not in harness.start_text(root)


def test_extra_is_cut_at_the_cap_on_a_whole_line_and_comments_go(tmp_path):
    root = _ws(tmp_path)
    harness.set_block(root, "alpha", "## Alpha\nA.", addon=True)
    lines = [f"- line {i:03d} " + "ü" * 20 for i in range(200)]
    _extra(root, "alpha", "<!-- hidden -->\r\n" + "\r\n".join(lines))
    extra = harness._addon_extra(root, "alpha")
    assert len(extra.encode("utf-8")) <= harness.EXTRA_CAP
    assert "hidden" not in extra and "\r" not in extra
    assert extra.endswith("ü\n") and all(re.fullmatch(r"- line \d{3} ü{20}", ln) for ln in extra.splitlines())
    assert 55 < len(extra.splitlines()) < 200


def test_extra_that_is_a_link_or_a_folder_is_ignored(tmp_path):
    root = _ws(tmp_path)
    harness.set_block(root, "alpha", "## Alpha\nA.", addon=True)
    outside = tmp_path / "outside.md"
    outside.write_text("- from outside\n", encoding="utf-8")
    d = root / ".orch" / "addons" / "alpha"
    d.mkdir(parents=True)
    try:
        (d / "AGENTS-extra.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        return  # no symlinks on this machine
    assert harness._addon_extra(root, "alpha") == ""
    (d / "AGENTS-extra.md").unlink()
    (d / "AGENTS-extra.md").mkdir()
    assert harness._addon_extra(root, "alpha") == ""


def test_copy_gets_the_text_in_its_own_agents_orch_md(tmp_path):
    root = _ws(tmp_path)
    harness.set_block(root, "alpha", "## Alpha\nA.", addon=True)
    _extra(root, "alpha", "- learned a thing\n")
    harness.rebuild(root)
    copy = tmp_path / "copy"
    copy.mkdir()
    assert harness.write_local_file(copy, "CLAUDE.local.md", None, harness_root=root)
    assert "- learned a thing" in (copy / harness.COPY_HARNESS / "AGENTS.orch.md").read_text(encoding="utf-8")


def test_core_harness_names_no_add_on():
    src = (Path(harness.__file__)).read_text(encoding="utf-8").lower()
    assert "lessons" not in src
