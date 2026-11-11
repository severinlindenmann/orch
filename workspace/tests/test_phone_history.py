import pytest

from orch import phone_view


@pytest.mark.parametrize("by", ["agent:relay from ph_abc", " Agent:Relay from ph_abc ",
                               "agent:phone", "agent:ph_abc", "agent: relay from ph_abc"])
def test_raw_phone_labels_never_render_as_people(proj, by):
    assert not phone_view.is_agent_history_author(by)
    assert phone_view._who(by) == ("orch", "agent")
    ticket = {"id": "t_abc123", "history": [
        {"at": "2026-11-09T09:00:00Z", "by": by, "text": "Approved", "via": "phone"}
    ]}
    history = phone_view.build(proj, ticket, [])["history_tail"]
    assert history == [{"at": "2026-11-09T09:00:00Z", "who": "orch",
                        "role": "agent", "text": "Approved"}]
