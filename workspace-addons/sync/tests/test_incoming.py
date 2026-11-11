import json
import subprocess

import pytest

from orch_sync import incoming, paths, repo

TICKET = 'tickets/t_abcdef.json'
ART = 'tickets/t_abcdef/artifacts/'


def commit_tree(root, entries):
    index = root / '.orch/run/sync/test-index'
    index.unlink(missing_ok=True)
    repo.git(root, 'read-tree', '--empty', index=index)
    for mode, path, data in entries:
        oid = (repo.git(root, 'rev-parse', 'HEAD').stdout.strip() if mode == '160000'
               else repo.git(root, 'hash-object', '-w', '--stdin', input=data).stdout.strip())
        repo.git(root, 'update-index', '--add', '--cacheinfo', mode, oid.decode(), path, index=index)
    tree = repo.git(root, 'write-tree', index=index).stdout.strip().decode()
    return repo.git(root, 'commit-tree', tree, '-p', 'HEAD', input=b'incoming\n').stdout.strip().decode()


def remote_ref(root, tmp_path, entries):
    oid = commit_tree(root, entries)
    bare = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    repo.set_remote(root, bare.as_uri())
    repo.git(root, 'push', 'origin', f'{oid}:refs/heads/orch-state')
    repo.git(root, 'fetch', 'origin')
    return 'origin/orch-state'


@pytest.mark.parametrize('mode,path,data', [
    ('120000', ART + 'link', b'/etc/passwd'), ('160000', ART + 'module', b''),
    ('100755', ART + 'exec', b'echo hello'), ('100644', '.gitattributes', b'* filter=evil'),
    ('100644', '.gitmodules', b'bad'), ('100644', '.gitignore', b'*'),
    ('100644', 'unknown', b'bad'), ('100644', ART + '.. ', b'bad'),
    ('100644', ART + 'credentials.txt', b'bad'), ('100644', TICKET, b'{"a":1,"a":2}'),
    ('100644', TICKET, b'{"a":' * 40 + b'0' + b'}' * 40), ('100644', TICKET, b'{"a":"\xff"}'),
])
def test_hostile(ready, tmp_path, mode, path, data):
    ref = remote_ref(ready, tmp_path, [(mode, path, data)])
    before = repo.git(ready, 'rev-parse', 'HEAD').stdout
    assert incoming.check(ready, ref)
    assert repo.git(ready, 'rev-parse', 'HEAD').stdout == before
    assert not (ready / '.orch/tickets').exists()


def test_good(ready, tmp_path):
    remote_ref(ready, tmp_path, [('100644', TICKET, b'{}'), ('100644', ART + 'report.txt', b'ok')])
    assert incoming.check(ready) == []


def test_ticket_deletion(ready, tmp_path):
    repo.git(ready, 'update-ref', 'HEAD', commit_tree(ready, [('100644', TICKET, b'{}')]))
    remote_ref(ready, tmp_path, [])
    assert 'ticket-deletion' in {p.code for p in incoming.check(ready)}


@pytest.mark.parametrize('total,deleted,blocked', [(5, 1, False), (5, 2, True), (100, 6, True)])
def test_artifact_deletions(ready, total, deleted, blocked):
    entries = [('100644', ART + str(i), b'x') for i in range(total)]
    repo.git(ready, 'update-ref', 'HEAD', commit_tree(ready, entries))
    ref = commit_tree(ready, entries[deleted:])
    assert ('needs-confirm' in {p.code for p in incoming.check(ready, ref)}) == blocked


@pytest.mark.parametrize('suffix', ['../secret', 'CON', 'nul.txt', '.env.prod', 'a.pem', 'a.key',
    'a.p8', 'a.p12', 'a.pfx', 'id_rsa.pub', 'id_ed25519', 'a.kdbx', 'credentials2',
    'a.', 'a ', '.git/config', '.GITIGNORE', 'é', 'a' * 101])
def test_paths(suffix):
    assert not paths.allowed(ART + suffix)


def test_collisions(ready):
    ref = commit_tree(ready, [('100644', ART + 'A/x', b'x'), ('100644', ART + 'a/y', b'y')])
    assert any(p.code == 'path' for p in incoming.check(ready, ref))


@pytest.mark.parametrize('data', [b'{"x":NaN}', b'{"x":1e999}', b'{"__proto__":{}}',
                                  json.dumps({'x': 'a' * 1_000_001}).encode()])
def test_json(data):
    with pytest.raises(ValueError):
        incoming.strict_load(data)


def test_size_and_ext(ready):
    ref = commit_tree(ready, [('100644', TICKET, b' ' * 1_000_001)])
    assert any(p.code == 'size' for p in incoming.check(ready, ref))
    ref = commit_tree(ready, [('100644', TICKET, b'{"ext":{"automation":{"cron":"* * * * *"}}}')])
    assert any(p.code == 'held-ext' for p in incoming.check(ready, ref))


def test_missing_ref(ready):
    assert incoming.check(ready, 'missing')


@pytest.mark.parametrize('name,data,code', [('secret.txt', b'orp_' + b'x' * 30, 'secret'),
                                         ('bundle.zip', b'PK\x03\x04', 'cannot-check')])
def test_full_blob_scan(ready, name, data, code):
    ref = commit_tree(ready, [('100644', ART + name, data)])
    assert any(p.code == code for p in incoming.check(ready, ref))


def test_object_size_limits(ready, monkeypatch):
    entries = [('100644', ART + str(i), b'x') for i in range(21)]
    ref = commit_tree(ready, entries)
    original = repo.git
    size = 25_000_000
    def fake(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args[0:2] == ('cat-file', '--batch-check'):
            result.stdout = b''.join(line.split()[0] + f' blob {size}\n'.encode()
                                     for line in result.stdout.splitlines())
        return result
    monkeypatch.setattr(repo, 'git', fake)
    assert any(p.message == 'Tree exceeds sync limit' for p in incoming.check(ready, ref))
    size = 26_000_000
    assert any(p.message == 'File exceeds sync limit' for p in incoming.check(ready, ref))


def test_file_count(ready, monkeypatch):
    monkeypatch.setattr(incoming, 'tree', lambda *_: [('100644', 'blob', 'unused', ART + 'a')] * 5001)
    assert incoming.check(ready, 'HEAD')[0].message == 'Too many files'


def test_ext_unchanged(ready):
    entries = [('100644', TICKET, b'{"ext":{"automation":{"cron":"daily"}}}')]
    repo.git(ready, 'update-ref', 'HEAD', commit_tree(ready, entries))
    assert incoming.check(ready, commit_tree(ready, entries)) == []


def test_ext_removal_held(ready):
    entries = [('100644', TICKET, b'{"ext":{"automation":{"cron":"daily"}}}')]
    repo.git(ready, 'update-ref', 'HEAD', commit_tree(ready, entries))
    ref = commit_tree(ready, [('100644', TICKET, b'{}')])
    assert any(p.code == 'held-ext' for p in incoming.check(ready, ref))
