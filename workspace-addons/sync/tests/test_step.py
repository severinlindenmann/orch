import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from orch import humanproof

from orch_sync import cli, repo, step

# clock-relative (a fixed day expires: sync's 24 h future check would pause everything): 12:00 of the old fixed
# day is "the start of this hour", the other times keep their distance from it.
BASE = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def at(hour, minute=0):
    return (BASE + timedelta(hours=hour - 12, minutes=minute)).strftime('%Y-%m-%dT%H:%M:%SZ')


NOW = at(12)
TICKET = 'tickets/t_abc123.json'
ART = 'tickets/t_abc123/artifacts/a.txt'


def ticket(**extra):
    return dict(schema='orch.ticket/1', id='t_abc123', title='A task', status='open',
                created_at=NOW, updated_at=NOW, checklist=[], refs=[], questions=[], history=[], **extra)


def save(root, path=TICKET, value=None):
    p = root / '.orch' / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(value if isinstance(value, bytes) else json.dumps(value or ticket()).encode())
    return p


def proof(root, target, monkeypatch):
    """A person's proof for `target` (op addon.act) on stdin, as the dashboard passes it with --proof-stdin."""
    key = humanproof.human_key(root)
    token = humanproof.mint(key, humanproof.new_payload('addon.act', target, 'human:Pat'))
    monkeypatch.setattr('sys.stdin', io.StringIO(token + '\n'))


def set_remote(root, remote, *args):
    """`orch sync set --mode remote --remote <remote>` with the person's set-remote proof (choosing the address)."""
    with pytest.MonkeyPatch.context() as m:
        proof(root, cli.remote_target(str(remote)), m)
        return cli.main(['--dir', str(root), 'set', '--mode', 'remote', '--remote', str(remote), '--proof-stdin', *args])


def configure(root, remote=None):
    if remote:
        assert set_remote(root, remote) == 0
        return
    assert cli.main(['--dir', str(root), 'set', '--mode', 'local']) == 0


def run(root):
    return step.run_once(root, 'test', now=NOW)


def success(root):
    state = run(root)
    assert state['last_error'] is None, state
    return state


def tracked(root):
    return set(repo.git(root, 'ls-tree', '-r', '--name-only', 'HEAD').stdout.decode().splitlines())


def test_local_allowlist(root):
    configure(root)
    save(root)
    for path in ('me/x', 'secrets/orp_local', 'run/x', 'tickets/t_abc123/artifacts/.env.local'):
        save(root, path, b'private')
    save(root, ART, b'x' * 26_000_000)
    save(root, 'tickets/t_general.json', dict(ticket(), id='t_general', general=True))
    state = success(root)
    assert tracked(root) == {TICKET}
    assert state['skipped'] == [f'{ART}: File exceeds 25 MB']
    assert state['last_ok'] == NOW


def test_local_only_items_are_quiet(root):
    configure(root)
    save(root, value=ticket(general=True))
    save(root, ART, b'private chat')
    for path in ('me/x', 'secrets/x', 'tickets/t_abc123/evidence/x',
                 'tickets/t_second/artifacts/.env.local'):
        save(root, path, b'private')
    for _ in range(2):
        state = success(root)
        assert state['skipped'] == []
        assert state['notices'] == []
        assert tracked(root) == set()


@pytest.mark.parametrize('path', [ART, TICKET])
@pytest.mark.parametrize('secret', ['orp_' + 'a' * 30, '-----BEGIN PRIVATE KEY-----'])
def test_secret_blocks_commit(root, path, secret):
    configure(root)
    value = dict(ticket(), note=secret) if path == TICKET else secret.encode()
    save(root, path, value)
    state = run(root)
    assert 'secret' in state['last_error']
    assert step.oid(root, 'HEAD') is None
    assert not repo.git(root, 'ls-files').stdout


@pytest.mark.parametrize('data', [b'PK\x03\x04archive', b'\x00\xffuncheckable'])
def test_cannot_check_blocks(root, data):
    configure(root)
    save(root, ART, data)
    assert 'cannot-check' in run(root)['last_error']
    assert step.oid(root, 'HEAD') is None


def test_missing_ticket_restored(root):
    configure(root)
    p = save(root)
    success(root)
    original = p.read_bytes()
    p.unlink()
    state = success(root)
    assert state['skipped'] == []
    assert state['notices'] == [f'Restored a missing ticket file: {TICKET}']
    assert p.read_bytes() == original
    assert tracked(root) == {TICKET}
    assert success(root)['notices'] == []
    assert tracked(root) == {TICKET}


def test_artifact_deletion_threshold(root):
    configure(root)
    save(root)
    p = save(root, ART, b'hello')
    success(root)
    head = step.oid(root, 'HEAD')
    p.unlink()
    assert run(root)["paused"]["files"] == [ART]
    assert ART in tracked(root)
    assert step.oid(root, "HEAD") == head
    from orch_sync.pause import resolve

    assert not resolve(root, ART, "mine", now=NOW).get("last_error")
    assert p.read_bytes() == b"hello"


def test_invalid_ticket_skipped(root):
    configure(root)
    save(root, value={'id': 't_abc123'})
    save(root, ART, b'ok')
    assert 'problem' in str(success(root)['skipped'])
    assert tracked(root) == set()
    assert not repo.git(root, 'ls-files').stdout


def test_stage_limits(root):
    configure(root)
    save(root, value=dict(ticket(), note='x' * 1_000_000))
    save(root, ART, b'private')
    assert 'problem' in str(success(root)['skipped'])
    assert tracked(root) == set()


def test_cli_now_and_status(root, capsys):
    configure(root)
    save(root)
    assert cli.main(['--dir', str(root), 'now', '--json']) == 0
    capsys.readouterr()
    assert cli.main(['--dir', str(root), 'status', '--json']) == 0
    state = json.loads(capsys.readouterr().out)
    assert state['last_ok'] and state['last_error'] is None and state['ahead'] == 1


def test_team_and_preview_checked_at_runtime(root):
    configure(root)
    settings = repo.safe(root, 'run/sync/settings.json')
    settings.write_text(json.dumps({'mode': 'remote', 'kind': 'team'}))
    assert 'Team' in run(root)['last_error']
    settings.write_text(json.dumps({'mode': 'remote', 'kind': 'private'}))
    assert 'preview' in run(root)['last_error']


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_unsafe_local_file_skipped(root, kind):
    import os
    configure(root)
    target = save(root, 'me/source', b'private bytes')
    p = root / '.orch' / ART
    p.parent.mkdir(parents=True)
    if kind == 'symlink':
        p.symlink_to(target)
    elif kind == 'hardlink':
        os.link(target, p)
    else:
        os.mkfifo(p)
    assert 'local' in str(success(root)['skipped']) or kind != 'symlink'
    assert ART not in tracked(root)


def test_full_staged_bytes_rescanned(root):
    configure(root)
    save(root)
    save(root, ART, b'safe')
    success(root)
    save(root, ART, b'orp_' + b'x' * 30)
    repo.git(root, 'add', '--', ART)
    repo.git(root, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'unsafe base')
    head = step.oid(root, 'HEAD')
    save(root)
    assert 'secret' in run(root)['last_error']
    assert step.oid(root, 'HEAD') == head
    assert not repo.git(root, 'diff', '--cached', '--no-ext-diff', '--no-textconv').stdout


def test_clock_is_commit_time(root):
    configure(root)
    save(root)
    success(root)
    result = repo.git(root, 'show', '--no-ext-diff', '--no-textconv', '-s', '--format=%aI %cI', 'HEAD')
    assert result.stdout.decode().strip().replace('+00:00', 'Z') == f'{NOW} {NOW}'


def test_case_collision_and_folder_limit(root):
    configure(root)
    save(root, ART, b'one')
    save(root, 'tickets/t_abc123/artifacts/A.TXT', b'two')
    # Case-sensitive filesystems retain both; on macOS assert the tree checker directly below.
    index = repo.local_dir(root) / 'test-index'
    repo.git(root, 'read-tree', '--empty', index=index)
    step.put(root, index, TICKET, step.encoded(ticket()))
    for path in (ART, 'tickets/t_abc123/artifacts/A.TXT'):
        step.put(root, index, path, b'text')
    tree = repo.git(root, 'write-tree', index=index).stdout.decode().strip()
    with pytest.raises(repo.Refused, match='Case-fold'):
        step.validate_tree(root, tree)
    repo.git(root, 'read-tree', '--empty', index=index)
    step.put(root, index, TICKET, step.encoded(ticket()))
    for n in range(201):
        step.put(root, index, f'tickets/t_abc123/artifacts/{n}.txt', b'text')
    tree = repo.git(root, 'write-tree', index=index).stdout.decode().strip()
    with pytest.raises(repo.Refused, match='Too much'):
        step.validate_tree(root, tree)


def test_step_lock_covers_state_write_and_recovers_scratch(root, monkeypatch):
    configure(root)
    save(root)
    abandoned = repo.safe(root, 'run/tmp-sync/old-step/index')
    abandoned.parent.mkdir(parents=True)
    abandoned.write_bytes(b'leftover index')
    write = step.write
    def checked(root, relative, data):
        if relative == 'run/sync/state.json':
            assert repo.safe(root, 'run/sync/step.lock').exists()
            assert 'already running' in run(root)['last_error']
        write(root, relative, data)
    monkeypatch.setattr(step, 'write', checked)
    success(root)
    assert not abandoned.exists()
    assert not repo.safe(root, 'run/sync/step.lock').exists()


@pytest.mark.parametrize('owner', [None, b'{"general": true,',
                                  step.encoded(ticket(general=True)), b'{"id":"t_abc123"}'])
def test_tree_refuses_artifact_without_valid_owner(root, owner):
    configure(root)
    index = repo.local_dir(root) / 'test-index'
    repo.git(root, 'read-tree', '--empty', index=index)
    step.put(root, index, ART, b'private chat')
    if owner is not None:
        step.put(root, index, TICKET, owner)
    tree = repo.git(root, 'write-tree', index=index).stdout.decode().strip()
    with pytest.raises(ValueError):
        step.validate_tree(root, tree)


@pytest.mark.parametrize('value', [ticket(general=True, unknownfield='x'), ticket(general=True)])
def test_general_ticket_preserves_existing_folder(root, value):
    configure(root)
    save(root)
    for n in range(7):
        save(root, f'tickets/t_abc123/artifacts/{n}.txt', b'local')
    success(root)
    before = step.entries(root, 'HEAD')
    save(root, value=value)
    assert success(root)['skipped'] == []
    assert step.entries(root, 'HEAD') == before
    assert set(repo.git(root, 'ls-files').stdout.decode().splitlines()) == set(before)
    assert (root / '.orch/tickets/t_abc123/artifacts/0.txt').read_bytes() == b'local'


@pytest.mark.parametrize(('count', 'removed', 'blocked'), [(5, 2, False), (6, 2, True),
                                                          (30, 6, True), (6, 1, False)])
def test_deletion_limits_per_ticket(count, removed, blocked):
    old = {f'tickets/t_abc123/artifacts/{n}.txt': None for n in range(count)}
    # Other tickets must not dilute the percentage for this ticket.
    old.update({f'tickets/t_second/artifacts/{n}.txt': None for n in range(100)})
    new = {p: e for p, e in old.items() if p not in
           {f'tickets/t_abc123/artifacts/{n}.txt' for n in range(removed)}}
    if blocked:
        with pytest.raises(repo.Refused, match='Many files'):
            step.deletions(old, new)
    else:
        step.deletions(old, new)



def test_unreadable_tracked_ticket_preserves_folder(root, monkeypatch):
    from pathlib import Path

    configure(root)
    save(root)
    save(root, ART, b'private chat')
    success(root)
    before = step.entries(root, 'HEAD')
    save(root, ART, b'changed locally')
    read_bytes = Path.read_bytes

    def unreadable(path):
        if path == root / '.orch' / TICKET:
            raise PermissionError('Ticket cannot be read')
        return read_bytes(path)

    monkeypatch.setattr(Path, 'read_bytes', unreadable)
    assert 'cannot be read' in str(success(root)['skipped'])
    assert step.entries(root, 'HEAD') == before
    assert set(repo.git(root, 'ls-files').stdout.decode().splitlines()) == {TICKET, ART}


def test_future_dated_remote_ticket_does_not_win(root):
    # Fable A15: updated_at 9999-... won every both-changed field, permanently.
    from orch_sync import pause

    base = ticket()
    local = dict(ticket(), title='Local title', updated_at=at(12, 30))
    remote = dict(ticket(), title='Remote title', updated_at='9999-12-31T23:59:59Z')
    with pytest.raises(pause.Pause, match='future'):
        step.merge_document(root, TICKET, base, local, remote, NOW)
    near = dict(remote, updated_at=at(12, 40))  # small clock skew is normal
    assert step.merge_document(root, TICKET, base, local, near, NOW)['title'] == 'Remote title'


def test_failed_write_leaves_no_temp_file(root, monkeypatch):
    # Fable A12: a temp file named like an artifact survived a failed write and was synced.
    import os

    configure(root)
    save(root)
    p = save(root, ART, b'old')
    os.chmod(p, 0o640)
    step.write(root, ART, b'new')
    assert p.read_bytes() == b'new' and (p.stat().st_mode & 0o777) == 0o640
    monkeypatch.setattr(step.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        step.write(root, ART, b'partial')
    assert sorted(x.name for x in p.parent.iterdir()) == ['a.txt']
    assert p.read_bytes() == b'new'


def test_merge_document_preserves_local_history_and_demotes_remote(root):
    local_line = {"at": NOW, "by": "human:lindenmann", "text": "Answered q1: yes"}
    remote_line = {"at": NOW, "by": "agent:relay from ph_abc", "text": "Approved"}
    local = dict(ticket(), history=[local_line])
    remote = dict(ticket(), history=[remote_line])
    out = step.merge_document(root, TICKET, ticket(), local, remote, NOW)
    assert local_line in out["history"]
    assert {**remote_line, "by": "agent:sync", "text": "(synced, not verified here) Approved"} in out["history"]
