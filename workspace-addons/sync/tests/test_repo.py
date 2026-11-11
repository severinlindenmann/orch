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
    assert cmd.index('--no-replace-objects') < cmd.index('status')


def test_old_git(root, monkeypatch):
    monkeypatch.setattr(repo, 'version_ok', lambda root: False)
    with pytest.raises(repo.Refused, match='Update git to 2.45.1 or newer'):
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


@pytest.mark.parametrize('name', ['commondir', 'gitdir', 'config.worktree',
                                 'objects/info/alternates', 'info/grafts', 'refs/replace/replacement'])
@pytest.mark.parametrize('link', [False, True])
def test_alternate_metadata(ready, name, link):
    path = ready / '.orch/.git' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if link:
        path.symlink_to(ready / 'missing')
    else:
        path.write_text('evil')
    with pytest.raises(repo.Refused, match='unexpected git settings'):
        repo.check(ready)


def test_evil_commondir(ready, tmp_path):
    bare = tmp_path / 'evil.git'
    canary = tmp_path / 'PWNED'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    subprocess.run(['git', '--git-dir', str(bare), 'config', 'core.sshCommand',
                    f'touch "{canary}"'], check=True)
    (ready / '.orch/.git/commondir').write_text(str(bare))
    with pytest.raises(repo.Refused, match='unexpected git settings'):
        repo.check(ready)
    assert not canary.exists()


def test_worktree_config(ready):
    repo.git(ready, 'config', 'extensions.worktreeConfig', 'true')
    (ready / '.orch/.git/config.worktree').write_text('[core]\nsshCommand = touch PWNED\n')
    with pytest.raises(repo.Refused, match='unexpected git settings'):
        repo.check(ready)


@pytest.mark.parametrize('version,ok', [('2.38.0', False), ('2.45.0', False), ('2.45.1', True),
                                      ('2.46.0', True), ('3.0.0', True)])
def test_minimum_git(root, monkeypatch, version, ok):
    monkeypatch.setattr(repo, 'git', lambda *a: subprocess.CompletedProcess(
        a, 0, f'git version {version}\n'.encode()))
    assert repo.version_ok(root) is ok


@pytest.mark.parametrize('url', ['https://user@host/repo', 'https://ghp_x@host/repo',
                                'https://@host/repo', 'http://user@host/repo'])
def test_http_userinfo(url):
    with pytest.raises(repo.Refused):
        repo.validate_url(url)


@pytest.mark.parametrize('scope,origin', [(b'local', b'file:/evil'),
                                        (b'worktree', b'file:.git/config')])
def test_config_origin_scope(ready, monkeypatch, scope, origin):
    original = repo.git
    def fake(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args[:2] == ('config', '--list'):
            result.stdout += scope + b'\0' + origin + b'\0user.name\nEvil\0'
        return result
    monkeypatch.setattr(repo, 'git', fake)
    with pytest.raises(repo.Refused, match='unexpected git settings'):
        repo.check(ready)


def test_common_dir_identity(ready, monkeypatch):
    original = repo.git
    def fake(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args == ('rev-parse', '--git-common-dir'):
            result.stdout = b'/evil\n'
        return result
    monkeypatch.setattr(repo, 'git', fake)
    with pytest.raises(repo.Refused, match='unexpected git settings'):
        repo.check(ready)


@pytest.mark.parametrize('native', [True, False])
def test_junction_detection(root, monkeypatch, native):
    from types import SimpleNamespace
    path = root / '.orch/run'
    path.mkdir()
    if native:
        monkeypatch.setattr(repo.os.path, 'isjunction', lambda p: p == path, raising=False)
    else:
        monkeypatch.delattr(repo.os.path, 'isjunction', raising=False)
        original = Path.lstat
        def lstat(p):
            info = original(p)
            return (SimpleNamespace(st_mode=info.st_mode,
                                    st_file_attributes=repo.stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    if p == path else info)
        monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(repo.Refused, match='links'):
        repo.safe(root, 'run/sync')


def test_recover_junction(ready, monkeypatch):
    scratch = ready / '.orch/run/tmp-sync'
    junction = scratch / 'junction'
    junction.mkdir(parents=True)
    monkeypatch.setattr(repo.os.path, 'isjunction', lambda p: p == junction, raising=False)
    removed = []
    monkeypatch.setattr(Path, 'unlink', lambda p: removed.append(p))
    monkeypatch.setattr(Path, 'rmdir', lambda p: removed.append(p))
    def forbidden(*args, **kwargs):
        raise AssertionError('must never traverse junction')
    monkeypatch.setattr(repo.shutil, 'rmtree', forbidden)
    repo.recover(ready)
    assert removed == [junction]
