import pytest

from orch import phone_view


@pytest.mark.parametrize(
    "by",
    [
        "agent:relay from ph_abc",
        " Agent:Relay from ph_abc ",
        "agent:phone",
        "agent:ph_abc",
        "agent: relay from ph_abc",
        "agent:\u200brelay from ph_abc",
        "agent:Severin Lindenmann",
    ],
)
def test_raw_phone_labels_never_render_as_people(proj, by):
    assert not phone_view.is_agent_history_author(by)
    assert phone_view._who(by) == ("orch", "agent")
    ticket = {
        "id": "t_abc123",
        "history": [{"at": "2026-11-09T09:00:00Z", "by": by, "text": "Approved", "via": "phone"}],
    }
    history = phone_view.build(proj, ticket, [])["history_tail"]
    assert history == [{"at": "2026-11-09T09:00:00Z", "who": "orch", "role": "agent", "text": "Approved"}]


@pytest.mark.parametrize(
    "by",
    [
        "agent:claude",
        "agent:sync",
        "agent:codex",
        "agent:automation",
        "agent:focus",
        "agent:my-agent_1.2",
        "ａｇｅｎｔ:ＣＯＤＥＸ",
    ],
)
def test_local_agent_ids_remain_agent_authors(by):
    assert phone_view.is_agent_history_author(by)
    assert phone_view._who(by)[1] == "agent"
