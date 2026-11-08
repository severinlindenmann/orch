import json

import pytest

from orch_focus import actions
from orch_focus.server import Tracker

from .conftest import TID, ticket
from .test_server import req


@pytest.mark.parametrize('claim,expected', [
    ({'agent': 'claude', 'label': 'Custom'}, 'Custom'),
    ({'agent': 'claude'}, 'Claude Code'),
    ({'agent': 'other'}, 'Other'),
    ({}, 'Claude Code'),
])
def test_qa2_agent_labels(claim, expected):
    v = Tracker._shape(ticket(), {}, claim, {}, [], True,
                       [{'name': 'claude', 'label': 'Claude Code', 'chosen': True}])
    assert v['run']['label'] == expected
    assert Tracker._shape(ticket(), {}, {}, {}, [], True)['run']['label'] == 'Agent'


def test_qa2_cached_lookups_and_failure(ws, monkeypatch):
    calls = []
    def orch(*args, **kwargs):
        calls.append(args[2])
        return 0, '[{"name":"claude","label":"Claude","chosen":true}]', ''
    monkeypatch.setattr(actions, 'orch', orch)
    tr = Tracker(ws, 'orch')
    assert tr.agents() == tr.agents()
    assert calls == [['agents', '--json']]
    def unavailable(*args, **kwargs):
        raise actions.Unavailable('offline')
    monkeypatch.setattr(actions, 'orch', unavailable)
    tr.lookup_cache.clear()
    assert tr.agents() == []
    assert tr.mobile() == {'available': False, 'on': False}
    assert tr.workspace() == ws.name


@pytest.mark.parametrize('data,available,on', [({'on': True}, True, True), ({'on': False}, True, False), ({'on': 1}, False, False), ({}, False, False)])
def test_qa2_mobile_endpoint_capabilities(server, monkeypatch, data, available, on):
    tr = server.RequestHandlerClass.keywords['tracker']
    monkeypatch.setattr(tr, 'lookup', lambda key, *a, **kw: data if key == 'mobile' else None)
    assert json.loads(req(server, 'GET', '/api/mobile')[1]) == {'available': available, 'on': on}
    v = json.loads(req(server, 'GET', f'/api/t/{TID}')[1])
    assert v['capabilities']['phone_mode'] is available
    assert v['phone_mode'] is on


def test_qa2_mobile_action_fence_and_argv(server, monkeypatch):
    assert actions.build_argv('mobile.set', {'on': True}) == ['relay', 'mobile', 'on', '--by', 'focus', '--json']
    assert actions.build_argv('mobile.set', {'on': False}) == ['relay', 'mobile', 'off', '--by', 'focus', '--json']
    for args in ({}, {'on': 1}, {'on': 'true'}, {'on': True, 'hours': 4}, {'on': True, 'by': 'someone'}):
        with pytest.raises(actions.BadRequest):
            actions.build_argv('mobile.set', args)
    body = {'op': 'mobile.set', 'args': {'on': True}}
    assert req(server, 'POST', '/api/act', body)[0] == 200
    assert req(server, 'POST', '/api/act', body, {'Origin': 'https://elsewhere.test'})[0] == 403
    assert req(server, 'POST', '/api/act', body, {'Sec-Fetch-Site': 'cross-site'})[0] == 403


def test_qa2_picker_fields(server, ws, monkeypatch):
    tr = server.RequestHandlerClass.keywords['tracker']
    monkeypatch.setattr(tr, 'lookup', lambda *a, **kw: [{'workspace': str(ws.resolve()), 'name': 'Pilatus'}])
    for status, questions, started, expected in [
        ('waiting', [{'answer': None}], False, 'Answer'),
        ('review', [], True, 'Check the result'), ('active', [], True, 'Working…'),
        ('open', [], False, 'Start'), ('open', [], True, 'Paused'), ('done', [], True, 'Done'),
    ]:
        (ws / '.orch/tickets' / f'{TID}.json').write_text(json.dumps(ticket(status=status, questions=questions, started=started)))
        data = json.loads(req(server, 'GET', '/api/tickets')[1])
        assert data['workspace'] == 'Pilatus'
        row = data['tickets'][0]
        assert row['next_step'] == expected
        assert row['question_count'] == len(questions)
