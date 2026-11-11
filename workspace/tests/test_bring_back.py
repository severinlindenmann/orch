"""B13 prerequisites: special attributes must be inspected before any merge."""

import hashlib
import subprocess

from orch import worktrees


def test_special_attributes_can_be_checked_without_running_filters(proj):
    subprocess.run(["git", "init", "-q", str(proj)], check=True, capture_output=True)
    attributes = proj / ".gitattributes"
    attributes.write_text("payload filter=lfs\n", encoding="utf-8")
    payload = proj / "payload"
    payload.write_bytes(b"local bytes must survive\n")
    paths = (attributes, payload)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

    rc, out, reason = worktrees._git(
        ["check-attr", "-z", "filter", "eol", "working-tree-encoding", "--", "payload"],
        proj,
        read_only=True,
        filters=False,  # Inspect actual attributes, not safegit's empty attribute tree.
        strip=False,
    )

    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before
    assert rc == 0, reason
    assert "payload\0filter\0lfs\0" in out
