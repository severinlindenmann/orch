"""ORCH-37: the dashboard can set and clear a ticket's release (ticket page Properties)."""

import json

from orch_dashboard import actions


def test_edit_passes_release_and_empty_clears():
    assert "--release=26" in actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "release": "26"})
    assert "--release=" in actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "release": ""})


def test_patch_accepts_release():
    argv = actions.build_argv(
        "ticket.patch", {"ticket": "t_abcdef", "data": {"release": "26"}, "if_revision": 1}
    )
    assert json.loads(argv[-1]) == {"release": "26"}
