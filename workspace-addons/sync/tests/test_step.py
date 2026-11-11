import json

import pytest

from orch_sync import cli, repo, step

NOW = '2026-11-11T12:00:00Z'
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


def configure(root, remote=None):
    args = ['--dir', str(root), 'set', '--mode', 'remote' if remote else 'local']
    assert cli.main(args + (['--remote', str(remote)] if remote else [])) == 0


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
    assert '25 MB' in str(state['skipped'])
    assert state['last_ok'] == NOW


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
    assert 'Restored' in str(success(root)['skipped'])
    assert p.read_bytes() == original


def test_artifact_deletion_threshold(root):
    configure(root)
    p = save(root, ART, b'hello')
    success(root)
    head = step.oid(root, 'HEAD')
    p.unlink()
    assert 'Many files' in run(root)['last_error']
    assert step.oid(root, 'HEAD') == head


def test_invalid_ticket_skipped(root):
    configure(root)
    save(root, value={'id': 't_abc123'})
    save(root, ART, b'ok')
    assert 'problem' in str(success(root)['skipped'])
    assert tracked(root) == {ART}


def test_stage_limits(root):
    configure(root)
    save(root, value=dict(ticket(), note='x' * 1_000_000))
    assert 'Too much' in run(root)['last_error']
    assert step.oid(root, 'HEAD') is None


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
    for path in (ART, 'tickets/t_abc123/artifacts/A.TXT'):
        step.put(root, index, path, b'text')
    tree = repo.git(root, 'write-tree', index=index).stdout.decode().strip()
    with pytest.raises(repo.Refused, match='Case-fold'):
        step.validate_tree(root, tree)
    repo.git(root, 'read-tree', '--empty', index=index)
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
