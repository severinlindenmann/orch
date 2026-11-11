import json
import subprocess

import pytest
from test_step import ART, NOW, TICKET, configure, run, save, success

from orch_sync import repo, step


@pytest.fixture
def machines(tmp_path, monkeypatch):
    monkeypatch.setenv('ORCH_SYNC_REMOTE_PREVIEW', '1')
    bare = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], capture_output=True, check=True)
    roots = [tmp_path / name for name in ('A', 'B')]
    for root in roots:
        (root / '.orch').mkdir(parents=True)
        configure(root, bare)
    return *roots, bare


def load(root):
    return json.loads((root / '.orch' / TICKET).read_text())


def edit(root, **values):
    save(root, value=load(root) | values)


def both(machines):
    a, b, bare = machines
    save(a)
    success(a)
    success(b)
    success(a)
    return a, b, bare


def remote_sha(bare):
    return subprocess.run(['git', '--git-dir', str(bare), 'rev-parse', 'orch-state'],
                          capture_output=True, check=True).stdout.strip()


def test_two_fields_status_counter(machines):
    a, b, _ = both(machines)
    edit(a, title='A title', updated_at='2026-11-11T13:00:00Z')
    edit(b, note='B note', updated_at='2026-11-11T14:00:00Z')
    save(a, 'ticket-counter.json', {'last': 10})
    save(b, 'ticket-counter.json', {'last': 20})
    success(a)
    success(b)
    success(a)
    assert load(a)['title'] == 'A title' and load(a)['note'] == 'B note'
    assert json.loads((a / '.orch/ticket-counter.json').read_text())['last'] == 20
    edit(a, status='done', updated_at='2026-11-11T15:00:00Z')
    edit(b, status='active', updated_at='2026-11-11T16:00:00Z')
    success(a)
    success(b)
    success(a)
    assert load(a)['status'] == load(b)['status'] == 'done'
    assert any(h['at'] == NOW and 'status' in h['text'] for h in load(b)['history'])


def test_offline_then_online(machines):
    a, b, bare = both(machines)
    moved = bare.with_name('offline.git')
    bare.rename(moved)
    edit(b, title='Offline edit')
    assert run(b)['last_error'] == 'offline'
    assert b'Offline edit' in repo.git(b, 'show', 'HEAD:' + TICKET).stdout
    moved.rename(bare)
    success(b)
    success(a)
    assert load(a)['title'] == 'Offline edit'


def hostile(a, bare, args):
    repo.git(a, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', *args)
    repo.git(a, 'push', '--force', 'origin', 'HEAD:orch-state')
    return remote_sha(bare)


def test_force_push_closed(machines):
    a, b, bare = both(machines)
    tree = step.oid(a, 'HEAD^{tree}')
    new = step.commit(a, tree, [], NOW)
    repo.git(a, 'update-ref', 'refs/heads/orch-state', new)
    repo.git(a, 'push', '--force', 'origin', 'HEAD:orch-state')
    before, content, tip = step.oid(b, 'HEAD'), load(b), remote_sha(bare)
    assert 'rewritten' in run(b)['last_error']
    assert step.oid(b, 'HEAD') == before and load(b) == content and remote_sha(bare) == tip


@pytest.mark.parametrize('path', [TICKET, ART])
def test_incoming_deletion_closed(machines, path):
    a, b, bare = both(machines)
    if path == ART:
        save(a, ART, b'artifact')
        success(a)
        success(b)
        success(a)
    repo.git(a, 'rm', '--', path)
    tip = hostile(a, bare, ['commit', '-m', 'delete'])
    head = step.oid(b, 'HEAD')
    before = (b / '.orch' / path).read_bytes()
    assert run(b)['last_error']
    assert step.oid(b, 'HEAD') == head
    assert (b / '.orch' / path).read_bytes() == before and remote_sha(bare) == tip


def test_ext_held_sessions_local(machines):
    a, b, _ = both(machines)
    edit(b, ext={'automation': {'enabled': False}})
    success(b)
    success(a)
    # Inject a remote block even though this machine would hold it on receipt.
    edit(a, ext={'automation': {'enabled': True}},
         sessions=[{'agent': 'codex', 'host': 'same-host', 'id': 'resume-me', 'last_used': NOW}])
    repo.git(a, 'add', '--', TICKET)
    hostile(a, machines[2], ['commit', '-m', 'incoming automation and session'])
    success(b)
    assert load(b)['ext']['automation'] == {'enabled': False}
    assert not load(b).get('sessions')
    held = list((b / '.orch/run/sync/held').glob('*.json'))
    assert any(json.loads(p.read_text())['value'] == {'enabled': True} for p in held)


def test_artifact_conflict_closed(machines):
    a, b, bare = both(machines)
    save(a, ART, b'base\n')
    success(a)
    success(b)
    success(a)
    save(a, ART, b'A\n')
    save(b, ART, b'B\n')
    success(a)
    tip = remote_sha(bare)
    assert 'Conflicting artifact' in run(b)['last_error']
    assert (b / '.orch' / ART).read_bytes() == b'B\n'
    assert remote_sha(bare) == tip


def test_agent_write_between_commit_apply(machines, monkeypatch):
    a, b, bare = both(machines)
    save(a, ART, b'original')
    success(a)
    success(b)
    success(a)
    save(a, ART, b'remote edit')
    success(a)
    apply = step.apply
    def agent_write(root, old, new, state):
        save(root, ART, b'agent edit')
        return apply(root, old, new, state)
    monkeypatch.setattr(step, 'apply', agent_write)
    tip = remote_sha(bare)
    assert 'busy' in run(b)['last_error']
    assert (b / '.orch' / ART).read_bytes() == b'agent edit'
    assert remote_sha(bare) == tip


def test_crash_before_apply_recovers(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, title='After crash')
    success(a)
    def crash(*args):
        raise RuntimeError('crash')
    with monkeypatch.context() as m:
        m.setattr(step, 'apply', crash)
        with pytest.raises(RuntimeError, match='crash'):
            run(b)
    assert (b / '.orch/run/sync/pending.json').exists()
    success(b)
    assert load(b)['title'] == 'After crash'
    success(b)
    assert load(b)['title'] == 'After crash'
    assert not (b / '.orch/run/sync/pending.json').exists()


def test_first_push_excludes_old_history(machines):
    a, _, bare = machines
    save(a, 'me/old-secret', b'orp_' + b'x' * 30)
    repo.git(a, 'add', '-f', '--', 'me/old-secret')
    repo.git(a, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'private history')
    old = step.oid(a, 'HEAD')
    save(a)
    success(a)
    reachable = subprocess.run(['git', '--git-dir', str(bare), 'rev-list', '--objects', 'orch-state'],
                               capture_output=True, check=True).stdout
    assert old.encode() not in reachable and b'old-secret' not in reachable
    assert repo.git(a, 'cat-file', '-t', old).stdout == b'commit\n'


def test_synced_files_cannot_enable_remote(machines):
    a, b, bare = both(machines)
    before = (b / '.orch/run/sync/settings.json').read_bytes()
    save(a, 'run/sync/settings.json', {'mode': 'remote', 'kind': 'team', 'remote': '/evil'})
    repo.git(a, 'add', '-f', '--', 'run/sync/settings.json')
    hostile(a, bare, ['commit', '-m', 'settings injection'])
    assert run(b)['last_error']
    assert (b / '.orch/run/sync/settings.json').read_bytes() == before


@pytest.mark.parametrize('payload', [b'orp_' + b'a' * 30, b'PK\x03\x04archive'])
def test_incoming_scan_blocks_before_commit(machines, payload):
    a, b, bare = both(machines)
    save(a, ART, payload)
    repo.git(a, 'add', '--', ART)
    tip = hostile(a, bare, ['commit', '-m', 'hostile bytes'])
    edit(b, title='Uncommitted local edit')
    head = step.oid(b, 'HEAD')
    assert run(b)['last_error']
    assert step.oid(b, 'HEAD') == head
    assert load(b)['title'] == 'Uncommitted local edit'
    assert not (b / '.orch' / ART).exists() and remote_sha(bare) == tip


def test_new_ticket_ext_and_session_held(machines):
    a, b, _ = machines
    from test_step import ticket
    save(a, value=ticket(ext={'scheduler': {'command': 'never-run'}},
                         sessions=[{'agent': 'codex', 'host': 'localhost', 'id': 'remote', 'last_used': NOW}]))
    success(a)
    success(b)
    assert not load(b).get('ext') and not load(b).get('sessions')
    assert list((b / '.orch/run/sync/held').glob('*.json'))


def test_non_ff_retries_once_from_fetch(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, title='A concurrent edit')
    edit(b, note='B concurrent edit')
    git = repo.git
    pushes = []
    def racing_git(root, *args, **kwargs):
        if root == b and args[0] == 'push':
            pushes.append(args)
            if len(pushes) == 1:
                success(a)
        return git(root, *args, **kwargs)
    monkeypatch.setattr(repo, 'git', racing_git)
    success(b)
    assert len(pushes) == 2
    assert load(b)['title'] == 'A concurrent edit' and load(b)['note'] == 'B concurrent edit'


def test_remote_url_change_orphans_again(machines, tmp_path):
    a, _, _ = both(machines)
    old = step.oid(a, 'HEAD')
    bare = tmp_path / 'second.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], capture_output=True, check=True)
    configure(a, bare)
    success(a)
    parents = repo.git(a, 'rev-list', '--parents', '-n', '1', 'HEAD').stdout.split()
    assert len(parents) == 1 and parents[0] != old.encode()


def test_partial_apply_crash_is_idempotent(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, title='New title')
    save(a, ART, b'new artifact')
    success(a)
    write = step.write
    replaced = []
    def crash_after_write(root, path, data):
        write(root, path, data)
        if path.startswith('tickets/'):
            replaced.append(path)
            raise RuntimeError('crash after replace')
    with monkeypatch.context() as m:
        m.setattr(step, 'write', crash_after_write)
        with pytest.raises(RuntimeError):
            run(b)
    assert len(replaced) == 1
    success(b)
    assert load(b)['title'] == 'New title' and (b / '.orch' / ART).read_bytes() == b'new artifact'


def test_key_clash_waits_for_pr5(machines):
    a, b, bare = both(machines)
    edit(a, key='AB1-1')
    success(a)
    success(b)
    from test_step import ticket
    save(b, 'tickets/t_second.json', dict(ticket(), id='t_second', key='AB1-1'))
    head, tip = step.oid(b, 'HEAD'), remote_sha(bare)
    assert 'key clash' in run(b)['last_error']
    assert step.oid(b, 'HEAD') == head and remote_sha(bare) == tip


def test_push_timeout_is_offline(machines, monkeypatch):
    a, _, _ = both(machines)
    edit(a, title='Pending push')
    git = repo.git
    def timeout(root, *args, **kwargs):
        if args[0] == 'push':
            raise repo.Refused('Git operation failed')
        return git(root, *args, **kwargs)
    monkeypatch.setattr(repo, 'git', timeout)
    assert run(a)['last_error'] == 'offline'
    assert b'Pending push' in repo.git(a, 'show', 'HEAD:' + TICKET).stdout
