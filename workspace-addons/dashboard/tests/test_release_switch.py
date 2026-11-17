"""ORCH-37: the Release switch on the ticket page marks a ticket as a release or takes the mark off."""

import pytest

from orch_dashboard import actions


@pytest.mark.parametrize(("on", "flag"), [(True, "--release=yes"), (False, "--release=no")])
def test_switch_builds_the_edit(on, flag):
    assert flag in actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "release": on, "if_revision": 3})


def test_switch_takes_only_true_or_false():
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "release": "yes"})
