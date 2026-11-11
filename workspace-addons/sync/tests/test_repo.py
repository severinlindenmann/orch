import hashlib
import subprocess
from pathlib import Path

import pytest

from orch_sync import paths, repo


def test_init(root):
    assert repo.state(root) == 'new'
    repo.ensure(root)
    assert repo.state(root) == 'ready' and repo.version_ok(root)
    assert (root / '.orch/.git/info/exclude').read_text().splitlines() == paths.NEVER_SYNCED
    assert repo.git(root, 'symbolic-ref', 'HEAD').stdout.strip() == b'refs/heads/orch-state'


@pytest.mark.parametrize('key,value', [('url.evil.insteadOf', 'https://'), ('include.path', '/evil'),
    ('credential.helper', '!touch canary'), ('core.sshCommand', 'evil'), ('remote.origin.uploadpack', 'evil')])
def test_config(ready, key, value):
    repo.git(ready, 'config', key, value)
    with pytest.raises(repo.Refused, match='unexpected git settings'):
        repo.check(ready)


def test_hook(ready):
    canary = ready / 'canary'
    hook = ready / '.orch/.git/hooks/pre-commit'
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f'#!/bin/sh\ntouch "{canary}"\n')
    hook.chmod(0o755)
    with pytest.raises(repo.Refused, match='hook'):
        repo.check(ready)
    repo.git(ready, 'commit', '--allow-empty', '-m', 'safe')
    assert not canary.exists()


@pytest.mark.parametrize('target', ['.orch', '.orch/.git'])
def test_links(root, tmp_path, target):
    p = root / target
    if p.exists():
        p.rmdir()
    dest = tmp_path / 'elsewhere'
    dest.mkdir()
    p.symlink_to(dest, target_is_directory=True)
    with pytest.raises(repo.Refused):
        repo.ensure(root)


def test_gitfile(root):
    (root / '.orch/.git').write_text('gitdir: /evil')
    with pytest.raises(repo.Refused):
        repo.ensure(root)


@pytest.mark.parametrize('url', ['ext::evil', 'fd::3', '-evil', 'git://host/repo',
    'https://user:password@host/repo', 'ftp://host/repo', 'user:password@host:path', 'relative/path'])
def test_urls(url):
    with pytest.raises(repo.Refused):
        repo.validate_url(url)


@pytest.mark.parametrize('url', ['https://host/repo', 'ssh://git@host/repo', 'git@host:path',
                                '/absolute/path', 'file:///tmp/bare'])
def test_good_urls(url):
    repo.validate_url(url)


def test_env_outer(root, monkeypatch):
    subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
    def hashes():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / '.git').rglob('*') if p.is_file()}
    before = hashes()
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        monkeypatch.setenv(key, '/evil')
    repo.ensure(root)
    assert hashes() == before


def test_move_and_adopt(root):
    subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
    (root / '.orch/unknown').write_text('personal')
    subprocess.run(['git', '-C', str(root), 'add', '.orch/unknown'], check=True)
    assert repo.state(root) == 'needs-move'
    with pytest.raises(repo.Refused, match='needs-move'):
        repo.ensure(root)
    repo.git(root, 'init', '-b', 'orch-state', '--template=')
    assert repo.state(root) == 'needs-adoption'
    with pytest.raises(repo.Refused, match='needs-adoption'):
        repo.ensure(root)


def test_wrapper_env(ready, monkeypatch):
    calls = []
    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, b'', b'')
    monkeypatch.setattr(repo.subprocess, 'run', run)
    for key in ('GIT_DIR', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM', 'SSH_ASKPASS'):
        monkeypatch.setenv(key, 'evil')
    for key in ('GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSL_CAINFO'):
        monkeypatch.setenv(key, 'kept')
    repo.git(ready, 'status')
    repo.git(ready, 'status', index=ready / 'index')
    cmd, kw = calls[0]
    assert cmd[:3] == ['git', '-C', str(ready / '.orch')]
    assert {k for k in kw['env'] if k.startswith('GIT_')} == {
        'GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSL_CAINFO', 'GIT_TERMINAL_PROMPT', 'GIT_ASKPASS'}
    assert kw['env']['GIT_ASKPASS'] == '' and kw['env']['LC_ALL'] == 'C'
    assert 'SSH_ASKPASS' not in kw['env']
    assert calls[1][1]['env']['GIT_INDEX_FILE'] == str(ready / 'index')
    assert all(opt in cmd for opt in repo.OPTIONS)


def test_old_git(root, monkeypatch):
    monkeypatch.setattr(repo, 'version_ok', lambda root: False)
    with pytest.raises(repo.Refused, match='Update git'):
        repo.ensure(root)


def test_recover(ready, tmp_path):
    outside = tmp_path / 'keep'
    outside.mkdir()
    (outside / 'precious').write_text('keep')
    scratch = ready / '.orch/run/tmp-sync'
    (scratch / 'step').mkdir(parents=True)
    (scratch / 'step/index').touch()
    (scratch / 'link').symlink_to(outside)
    repo.recover(ready)
    assert list(scratch.iterdir()) == []
    assert (outside / 'precious').read_text() == 'keep'


def test_lint_boundary():
    for p in Path(repo.__file__).parent.glob('*.py'):
        if p.name not in ('repo.py', 'orchcli.py'):
            assert 'subprocess' not in p.read_text()


def test_remote_and_attributes(ready, tmp_path):
    bare = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    repo.set_remote(ready, bare.as_uri())
    assert repo.git(ready, 'config', 'remote.origin.url').stdout.decode().strip() == bare.as_uri()
    (ready / '.orch/.git/info/attributes').write_text('* filter=evil')
    with pytest.raises(repo.Refused, match='attributes'):
        repo.check(ready)


def test_version_without_root():
    assert repo.version_ok()
