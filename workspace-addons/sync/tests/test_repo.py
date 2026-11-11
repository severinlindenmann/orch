import hashlib
import itertools
import json
import re
import subprocess
from pathlib import Path

import pytest
from orch import safegit

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


@pytest.mark.parametrize('url', ['ext::evil', 'ext::sh -c touch% /tmp/PWNED', 'fd::3', 'fd::3,4', '-evil',
    'git://host/repo', 'http://host/repo', 'https://user:password@host/repo', 'ftp://host/repo',
    'user:password@host:path', 'relative/path', 'file://localhost/tmp/bare', 'file://host/tmp/bare',
    'testgit::/tmp/x', 'persistent-https://host/repo'])
def test_urls(url):
    with pytest.raises(repo.Refused):
        repo.validate_url(url)


@pytest.mark.parametrize('url', ['https://host/repo', 'ssh://git@host/repo', 'git@host:path'])
@pytest.mark.parametrize('kind', ['normal', 'test'])
def test_good_urls(url, kind, monkeypatch):
    monkeypatch.setattr(repo.humanproof, 'install_kind', lambda: kind)
    repo.validate_url(url)


LOCAL_URLS = ['/absolute/path', 'file:///tmp/bare']
NEEDS = re.escape(repo.NEEDS_NETWORK)


@pytest.mark.parametrize('url', LOCAL_URLS)
def test_local_urls_only_on_a_test_install(url, monkeypatch):
    repo.validate_url(url)  # the suite is a test install
    for kind in ('normal', 'dev'):
        monkeypatch.setattr(repo.humanproof, 'install_kind', lambda k=kind: k)
        with pytest.raises(repo.RemoteRefused, match=NEEDS):
            repo.validate_url(url)


@pytest.mark.parametrize('kind', ['normal', 'test'])
@pytest.mark.parametrize('url', ['ext::sh -c touch% PWNED', 'fd::3', 'git://host/repo'])
def test_refused_transports_never_reach_git(ready, tmp_path, url, kind, monkeypatch):
    # Fable B1: refused for the configured remote and for an address given directly to push/fetch/ls-remote,
    # on a real install and on a test install alike.
    monkeypatch.setattr(repo.humanproof, 'install_kind', lambda: kind)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(repo.Refused, match=NEEDS):
        repo.set_remote(ready, url)
    for args in (('push', url, 'HEAD:refs/heads/orch-state'), ('fetch', url), ('ls-remote', url)):
        with pytest.raises(repo.Refused, match=NEEDS):
            repo.git(ready, *args)
    repo.git(ready, 'config', 'remote.origin.url', url)
    with pytest.raises(repo.Refused):
        repo.check(ready)
    with pytest.raises(repo.Refused, match=NEEDS):
        repo.fetch(ready)
    assert not (tmp_path / 'PWNED').exists()


@pytest.mark.parametrize('option', ['--receive-pack=evil', '--upload-pack=evil', '--exec=evil', '-uevil',
                                    '--repo=/evil'])
def test_callers_never_choose_the_remote_program(ready, tmp_path, option):
    with pytest.raises(repo.Refused):
        repo.git(ready, 'push', option, str(tmp_path), 'HEAD:refs/heads/orch-state')


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


def test_interrupted_init_recovers(root, monkeypatch):
    # Fable B8: a refusal or crash between `git init` and the marker left needs-adoption forever.
    real = repo.check

    def refused(root):
        raise repo.Refused('unexpected git settings')

    monkeypatch.setattr(repo, 'check', refused)
    with pytest.raises(repo.Refused):
        repo.ensure(root)
    monkeypatch.setattr(repo, 'check', real)
    assert repo.state(root) == 'new'
    repo.ensure(root)
    assert repo.state(root) == 'ready'


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
    base = safegit.env(ready / '.orch', ready, safegit.trivial('true', ready / '.orch', ready))
    assert {k for k in kw['env'] if k.startswith('GIT_')} == {
        'GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSL_CAINFO', *(k for k in base if k.startswith('GIT_'))}
    own = ('GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSL_CAINFO', 'SSH_ASKPASS')  # sync's extras: passed / removed
    assert {k: kw['env'][k] for k in base if k not in own} == {k: v for k, v in base.items() if k not in own}
    assert kw['env']['GIT_SSH'] == 'kept' and 'evil' not in kw['env'].values()
    assert kw['env']['GIT_TERMINAL_PROMPT'] == '0' and kw['env']['LC_ALL'] == 'C'
    assert 'SSH_ASKPASS' not in kw['env']
    assert calls[1][1]['env']['GIT_INDEX_FILE'] == str(ready / 'index')
    assert all(opt in cmd for opt in repo.OPTIONS)
    assert cmd.index('--no-replace-objects') < cmd.index('status')


def test_wrapper_builds_on_safegit_base(ready, monkeypatch):
    # One hardening base, no drift: every -c pair of core safegit's base (whatever it holds now or later) is in
    # every sync git argv, before sync's own extras, and the environment is safegit's.
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, b'', b'')

    monkeypatch.setattr(repo.subprocess, 'run', run)
    repo.git(ready, 'status')
    cmd, kw = calls[0]
    true = safegit.trivial('true', ready / '.orch', ready)
    base = safegit.base_args(true)
    assert base and len(base) % 2 == 0
    pairs = list(itertools.pairwise(cmd))
    for i in range(0, len(base), 2):
        assert (base[i], base[i + 1]) in pairs
    start = cmd.index(base[1])
    assert cmd[start - 1:start - 1 + len(base)] == base  # the whole base, in order, as one block
    for extra in repo.OPTIONS:
        assert cmd.index(extra) > start  # sync's extras come after (and so on top of) the base
    for key, value in safegit.env(ready / '.orch', ready, true).items():
        if key not in repo.ENV_PASSED and key != 'SSH_ASKPASS':
            assert kw['env'][key] == value
    # a later sync -c never switches the base's protections back off, except the documented network ssh
    later = [cmd[i + 1] for i in range(start - 1 + len(base), len(cmd) - 1) if cmd[i] == '-c']
    base_keys = {base[i + 1].split('=', 1)[0] for i in range(0, len(base), 2)}
    assert {v.split('=', 1)[0] for v in later} & base_keys <= {'core.hooksPath'}


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


HOSTILE_HOOKS = ('pre-receive', 'update', 'post-receive', 'post-update', 'reference-transaction',
                 'push-to-checkout', 'proc-receive')


def hostile_remote(tmp_path):
    """A bare local remote whose every receive-side hook is executable and writes a canary."""
    bare = tmp_path / 'evil.git'
    canary = tmp_path / 'PWNED'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    for name in HOSTILE_HOOKS:
        hook = bare / 'hooks' / name
        hook.write_text(f'#!/bin/sh\necho {name} >> "{canary}"\n')
        hook.chmod(0o755)
    return bare, canary


def network_calls(ready, url):
    """Every push/fetch/ls-remote form sync can make to `url` (configured as origin and given directly)."""
    return (lambda: repo.git(ready, 'push', 'origin', 'HEAD:refs/heads/orch-state'),
            lambda: repo.git(ready, 'push', '--force', url, 'HEAD:refs/heads/other'),
            lambda: repo.fetch(ready),
            lambda: repo.git(ready, 'fetch', url, 'refs/heads/other'),
            lambda: repo.git(ready, 'ls-remote', 'origin'))


@pytest.mark.parametrize('form', ['path', 'uri'])
def test_local_remote_with_hooks_is_refused_before_any_git(ready, tmp_path, form):
    # A local remote with any non-sample hook is refused by the read-only inspection; git never runs.
    bare, canary = hostile_remote(tmp_path)
    url = str(bare) if form == 'path' else bare.as_uri()
    repo.set_remote(ready, url)
    for call in network_calls(ready, url):
        with pytest.raises(repo.RemoteRefused, match=re.escape(repo.LOCAL_REMOTE_REFUSED)):
            call()
    assert not canary.exists()
    # the hooks are live: a plain push (without sync's wrapper) does run them
    subprocess.run(['git', '-C', str(ready / '.orch'), 'push', url, 'HEAD:refs/heads/control'],
                   check=True, capture_output=True)
    assert canary.exists()


@pytest.mark.parametrize('form', ['path', 'uri'])
def test_pack_program_keeps_hooks_off_even_without_the_inspection(ready, tmp_path, form, monkeypatch):
    # Fable B1, layer (b) on its own: git runs a local remote's own hooks on push/fetch; our -c never reaches that
    # process. Sync names the remote-side program itself with hooks off, so no hook ever runs.
    monkeypatch.setattr(repo, 'inspect_local', lambda root, url: None)
    bare, canary = hostile_remote(tmp_path)
    url = str(bare) if form == 'path' else bare.as_uri()
    repo.set_remote(ready, url)
    repo.check(ready)
    head = repo.git(ready, 'rev-parse', 'HEAD').stdout.strip()
    for call in network_calls(ready, url):
        call()
    assert repo.git(ready, 'rev-parse', 'refs/remotes/origin/orch-state').stdout.strip() == head
    assert subprocess.run(['git', '--git-dir', str(bare), 'rev-parse', 'orch-state'], capture_output=True,
                          check=True).stdout.strip() == head
    assert not canary.exists()


def hostile_config_remote(tmp_path, *settings):
    """A bare local remote whose OWN config names a command (no hooks): core.alternateRefsCommand runs when
    receive-pack/upload-pack advertise the refs of an alternate, so it gets one."""
    other = tmp_path / 'other.git'
    bare = tmp_path / 'cfg.git'
    canary = tmp_path / 'canary'
    for repository in (other, bare):
        subprocess.run(['git', 'init', '--bare', str(repository)], check=True, capture_output=True)
    (bare / 'objects/info/alternates').write_text(f'{other / "objects"}\n')
    for key, value in settings or (('core.alternateRefsCommand', f'touch "{canary}"'),):
        subprocess.run(['git', '--git-dir', str(bare), 'config', key, value.format(canary=canary)], check=True)
    return bare, canary


@pytest.mark.parametrize('form', ['path', 'uri'])
def test_normal_install_refuses_local_remotes_everywhere(ready, tmp_path, form, normal_install, capsys,
                                                         monkeypatch):
    # A real install never runs git inside a peer-controlled local repository: refused at
    # `orch sync set --remote`, in set_remote, and at every fetch/push, also for a local URL stored before.
    from orch_sync import cli

    monkeypatch.setenv('ORCH_SYNC_REMOTE_PREVIEW', '1')
    bare, canary = hostile_config_remote(tmp_path)
    url = str(bare) if form == 'path' else bare.as_uri()
    with pytest.raises(repo.RemoteRefused, match=NEEDS):
        repo.validate_url(url)
    with pytest.raises(repo.RemoteRefused, match=NEEDS):
        repo.set_remote(ready, url)
    capsys.readouterr()
    assert cli.main(['--dir', str(ready), 'set', '--mode', 'local', '--remote', url]) != 0
    assert repo.NEEDS_NETWORK in capsys.readouterr().err
    repo.git(ready, 'config', 'remote.origin.url', url)  # stored by an earlier version
    for call in network_calls(ready, url):
        with pytest.raises(repo.RemoteRefused, match=NEEDS):
            call()
    with pytest.raises(repo.Refused, match=NEEDS):
        repo.check(ready)
    assert not canary.exists()


def test_normal_install_step_reports_a_stored_local_remote(root, tmp_path, monkeypatch):
    from orch_sync import cli, step

    monkeypatch.setenv('ORCH_SYNC_REMOTE_PREVIEW', '1')
    bare, canary = hostile_config_remote(tmp_path)
    assert cli.main(['--dir', str(root), 'set', '--mode', 'remote', '--remote', str(bare)]) == 0  # test install
    monkeypatch.setattr(repo.humanproof, 'install_kind', lambda: 'normal')  # then a real install reads it
    calls = recorded(monkeypatch, fake_network=False)
    state = step.run_once(root, 'test')
    assert state['last_error'] == repo.NEEDS_NETWORK
    assert not [c for c, _ in calls if {'push', 'fetch', 'ls-remote'} & set(c)] and not canary.exists()


@pytest.mark.parametrize('settings', [
    (),  # core.alternateRefsCommand + an alternate
    (('core.fsmonitor', 'touch "{canary}"'),),
    (('include.path', '{canary}.inc'),),
    (('includeIf.gitdir:/.path', '{canary}.inc'),),
    (('receive.autogc', 'true'), ('gc.auto', '1')),
    (('uploadpack.packObjectsHook', 'touch "{canary}"'),),
    (('core.bare', 'false'),),
])
@pytest.mark.parametrize('form', ['path', 'uri'])
def test_test_install_inspection_refuses_a_hostile_local_remote(ready, tmp_path, form, settings):
    # Read-only inspection before every local push/fetch; git never runs inside the remote.
    bare, canary = hostile_config_remote(tmp_path, *settings)
    if settings:
        (bare / 'objects/info/alternates').unlink()  # the config alone is refused
    url = str(bare) if form == 'path' else bare.as_uri()
    repo.set_remote(ready, url)
    for call in network_calls(ready, url):
        with pytest.raises(repo.RemoteRefused, match=re.escape(repo.LOCAL_REMOTE_REFUSED)):
            call()
    assert not canary.exists()
    if not settings:  # the remote is truly hostile: a plain push (without sync's wrapper) runs the command
        subprocess.run(['git', '-C', str(ready / '.orch'), 'push', url, 'HEAD:refs/heads/control'],
                       check=False, capture_output=True)
        assert canary.exists()


@pytest.mark.parametrize('name', ['objects/info/alternates', 'objects/info/http-alternates', '.git',
                                  'commondir', 'config.worktree'])
def test_test_install_inspection_refuses_indirection(ready, tmp_path, name):
    bare = tmp_path / 'r.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    (bare / name).write_text(f'{tmp_path}\n')
    repo.set_remote(ready, str(bare))
    with pytest.raises(repo.RemoteRefused, match=re.escape(repo.LOCAL_REMOTE_REFUSED)):
        repo.fetch(ready)


def test_test_install_inspection_refuses_a_linked_config(ready, tmp_path):
    bare = tmp_path / 'r.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    (tmp_path / 'config').write_bytes((bare / 'config').read_bytes())
    (bare / 'config').unlink()
    (bare / 'config').symlink_to(tmp_path / 'config')
    repo.set_remote(ready, str(bare))
    with pytest.raises(repo.RemoteRefused, match=re.escape(repo.LOCAL_REMOTE_REFUSED)):
        repo.fetch(ready)


def test_pack_program_overrides_command_keys_even_without_the_inspection(ready, tmp_path, monkeypatch):
    # The remote's core.alternateRefsCommand is overridden on the pack program's command line, so even an
    # uninspected hostile remote runs nothing.
    monkeypatch.setattr(repo, 'inspect_local', lambda root, url: None)
    bare, canary = hostile_config_remote(tmp_path)
    repo.set_remote(ready, str(bare))
    for call in network_calls(ready, str(bare)):
        call()
    assert not canary.exists()


@pytest.mark.parametrize('form', ['path', 'uri'])
def test_test_install_clean_local_remote_push_and_fetch(ready, tmp_path, form):
    bare = tmp_path / 'clean.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    url = str(bare) if form == 'path' else bare.as_uri()
    repo.set_remote(ready, url)
    head = repo.git(ready, 'rev-parse', 'HEAD').stdout.strip()
    for call in network_calls(ready, url):
        call()
    assert repo.git(ready, 'rev-parse', 'refs/remotes/origin/orch-state').stdout.strip() == head
    assert subprocess.run(['git', '--git-dir', str(bare), 'rev-parse', 'orch-state'], capture_output=True,
                          check=True).stdout.strip() == head


def test_push_reads_the_porcelain_result(ready, tmp_path):
    # A rejection is read from git's --porcelain lines on stdout, never from stderr (the remote side can
    # write there, and it depends on git's language).
    bare = tmp_path / 'clean.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    repo.set_remote(ready, str(bare))
    head = repo.git(ready, 'rev-parse', 'HEAD').stdout.decode().strip()
    assert repo.push(ready, head) is True
    repo.git(ready, 'commit', '--allow-empty', '-m', 'mine')
    other = repo.git(ready, 'commit-tree', 'HEAD^{tree}', input=b'unrelated\n').stdout.decode().strip()
    assert repo.push(ready, other) is False  # not a fast forward: someone pushed first
    assert subprocess.run(['git', '--git-dir', str(bare), 'rev-parse', 'orch-state'], capture_output=True,
                          check=True).stdout.decode().strip() == head


def test_pack_flags_only_for_local_remotes(ready, tmp_path, monkeypatch):
    calls = []
    real = subprocess.run

    def run(cmd, **kw):
        if not {'push', 'fetch', 'ls-remote'} & set(cmd):
            return real(cmd, **kw)
        calls.append((cmd, kw['env']))
        return subprocess.CompletedProcess(cmd, 0, b'', b'')

    subprocess.run(['git', 'init', '--bare', str(tmp_path / 'r.git')], check=True, capture_output=True)
    monkeypatch.setattr(repo.subprocess, 'run', run)
    null = '/dev/null' if repo.os.name != 'nt' else 'NUL'
    # every command-bearing key the peer's config could set is overridden on the pack program
    over = (f'-c core.hooksPath={null} -c core.alternateRefsCommand= -c core.alternateRefsPrefixes= '
            '-c core.fsmonitor=false -c receive.autogc=false -c gc.auto=0 -c transfer.fsckObjects=true')
    for url, local in ((str(tmp_path / 'r.git'), True), ((tmp_path / 'r.git').as_uri(), True),
                       ('https://host/repo', False), ('git@host:path', False), ('ssh://host/repo', False)):
        repo.set_remote(ready, url)
        calls.clear()
        repo.git(ready, 'push', 'origin', 'HEAD:refs/heads/orch-state')
        repo.git(ready, 'fetch', '--no-tags', 'origin')
        repo.git(ready, 'ls-remote', url)
        (push, push_env), (fetch, fetch_env), (ls, ls_env) = calls
        receive = f'--receive-pack=git {over} receive-pack'
        upload = f'--upload-pack=git {over} upload-pack'
        assert (receive in push) is local and (upload in fetch) is local and (upload in ls) is local
        assert ('protocol.file.allow=always' in push) is local
        assert ('protocol.file.allow=never' in fetch) is not local
        for env in (push_env, fetch_env, ls_env):  # the pack program reads no system or global config
            assert (env.get('GIT_CONFIG_NOSYSTEM') == '1' and env.get('GIT_CONFIG_GLOBAL') == null) is local
        if local:
            assert push[push.index('push') + 1] == receive and fetch[fetch.index('fetch') + 1] == upload


REMOTE = 'https://127.0.0.1:9/owner/private.git'  # nothing listens on port 9: refused at once
REMOTE_SETTINGS = json.dumps({'mode': 'remote', 'remote': REMOTE, 'kind': 'private', 'interval': 15})


def recorded(monkeypatch, fake_network=True):
    """Every git command line and environment; network calls answered without a network when `fake_network`."""
    calls, real = [], subprocess.run

    def run(cmd, **kw):
        calls.append((cmd, kw.get('env') or {}))
        if fake_network and {'push', 'fetch', 'ls-remote'} & set(cmd):
            return subprocess.CompletedProcess(cmd, 0, b'', b'')
        return real(cmd, **kw)

    monkeypatch.setattr(repo.subprocess, 'run', run)
    return calls


def helpers_in(cmd):
    return [cmd[i + 1].split('=', 1)[1] for i, v in enumerate(cmd[:-1])
            if v == '-c' and cmd[i + 1].startswith('credential.helper=')]


def test_global_credential_helper_only_for_calls_to_the_configured_remote(ready, monkeypatch):
    # A private https remote needs the person's own git login. core safegit empties the helper; sync passes
    # back the person's GLOBAL helpers on fetch/push/ls-remote to `origin` only.
    home = Path(repo.os.environ['HOME'])
    (home / '.gitconfig').write_text('[credential]\n\thelper =\n\thelper = store --file=/nowhere/creds\n'
                                     '\thelper = osxkeychain\n')
    repo.set_remote(ready, REMOTE)
    canary = ready / 'canary'
    with (ready / '.orch/.git/config').open('a') as f:  # what an agent could write into the repository
        f.write(f'[credential]\n\thelper = !touch {canary}\n')
    assert repo.credential_helpers(ready) == ['', 'store --file=/nowhere/creds', 'osxkeychain']
    calls = recorded(monkeypatch)
    repo.git(ready, 'push', 'origin', 'HEAD:refs/heads/orch-state')
    repo.fetch(ready)
    repo.git(ready, 'ls-remote', 'origin')
    repo.git(ready, 'ls-remote', REMOTE)  # an address given directly is not the configured remote
    repo.git(ready, 'rev-parse', 'HEAD')
    repo.git(ready, 'commit', '--allow-empty', '-m', 'local')
    person = ['', 'store --file=/nowhere/creds', 'osxkeychain']
    network = [(c, e) for c, e in calls if {'push', 'fetch', 'ls-remote'} & set(c)]
    # push; fetch = its ls-remote --exit-code probe + the fetch; ls-remote origin; ls-remote <address>
    assert len(network) == 5
    assert '--exit-code' in network[1][0] and 'fetch' in network[2][0]
    for cmd, env in network[:4]:
        # the base's reset first, then the person's helpers in order; never the repository's
        assert helpers_in(cmd) == ['', *person] and f'!touch {canary}' not in ' '.join(cmd)
        assert env['GIT_TERMINAL_PROMPT'] == '0' and 'SSH_ASKPASS' not in env
        assert env['GIT_ASKPASS'] == safegit.trivial('true', ready / '.orch', ready)
    assert helpers_in(network[4][0]) == ['']
    local = [c for c, _ in calls if not {'push', 'fetch', 'ls-remote'} & set(c)]
    assert len(local) >= 3 and all(helpers_in(c) == [''] for c in local)  # local calls: the base's reset only
    assert not canary.exists()
    # and repo.check refuses the planted repository helper outright (it is not a key sync writes)
    with pytest.raises(repo.Refused, match='unexpected git settings'):
        repo.check(ready)


@pytest.mark.parametrize('helper', ['!touch /tmp/x', '/usr/local/bin/evil', 'store --file=$(id)', 'evil-helper'])
def test_a_global_helper_that_is_not_gits_own_gives_no_login(ready, helper):
    # Opus hard3 #8: ~/.gitconfig is writable by agents too; a `!command` or a program path would run inside
    # sync with access to the guarded home. Only git's own helpers by name, with plain options.
    home = Path(repo.os.environ['HOME'])
    (home / '.gitconfig').write_text(f'[credential]\n\thelper = osxkeychain\n\thelper = {helper}\n')
    assert repo.credential_helpers(ready) == []


def test_repository_credential_helper_stops_sync_before_any_network(root, monkeypatch):
    from orch_sync import cli, step

    monkeypatch.setenv('ORCH_SYNC_REMOTE_PREVIEW', '1')
    assert cli.main(['--dir', str(root), 'set', '--mode', 'local']) == 0
    repo.set_remote(root, REMOTE)
    (root / '.orch/run/sync/settings.json').write_text(REMOTE_SETTINGS)
    canary = root / 'canary'
    with (root / '.orch/.git/config').open('a') as f:
        f.write(f'[credential]\n\thelper = !touch {canary}\n')
    calls = recorded(monkeypatch)
    state = step.run_once(root, 'test')
    assert state['last_error'] == 'unexpected git settings'
    assert not [c for c, _ in calls if {'push', 'fetch', 'ls-remote'} & set(c)] and not canary.exists()


def test_no_helper_https_fetch_is_offline_without_a_prompt(root, monkeypatch):
    from orch_sync import cli, step

    monkeypatch.setenv('ORCH_SYNC_REMOTE_PREVIEW', '1')
    assert cli.main(['--dir', str(root), 'set', '--mode', 'local']) == 0
    (root / '.orch/run/sync/settings.json').write_text(REMOTE_SETTINGS)
    (root / '.orch/tickets').mkdir(parents=True, exist_ok=True)
    assert repo.credential_helpers(root) == []
    calls = recorded(monkeypatch, fake_network=False)
    state = step.run_once(root, 'test')
    assert state['last_error'] == 'offline'
    # fetch first asks whether the branch is there (ls-remote --exit-code): unreachable = offline, no fetch
    (cmd, env), = [(c, e) for c, e in calls if {'fetch', 'ls-remote'} & set(c)]
    assert 'ls-remote' in cmd and '--exit-code' in cmd
    assert helpers_in(cmd) == [''] and env['GIT_TERMINAL_PROMPT'] == '0'
    assert env['GIT_ASKPASS'] == safegit.trivial('true', root / '.orch', root)


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
