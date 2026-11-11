"""All git execution lives here. No outer-repository mutations or automatic adoption."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .paths import NEVER_SYNCED


class Refused(ValueError):
    pass


CONFIG = re.compile(r'core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)'
                    r'|remote\.origin\.(url|fetch)|branch\.orch-state\.(remote|merge)|user\.(name|email)')
OPTIONS = ('protocol.allow=never', 'protocol.https.allow=always', 'protocol.ssh.allow=always',
           'protocol.file.allow=always', 'submodule.recurse=false', 'fetch.recurseSubmodules=false',
           'transfer.fsckObjects=true', 'core.protectNTFS=true', 'core.protectHFS=true',
           'core.fsmonitor=false', 'commit.gpgsign=false', 'core.symlinks=false')


def is_link(path):
    """Include junctions and other Windows reparse points without following them."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    junction = getattr(os.path, 'isjunction', None)
    return (stat.S_ISLNK(info.st_mode) or (junction is not None and junction(path))
            or bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def safe(root, relative):
    """Reject links in every component before local reads/writes."""
    p = Path(root).absolute()
    for part in Path('.orch', relative).parts:
        p /= part
        if is_link(p):
            raise Refused('Sync paths must not be links')
    return p


def local_dir(root):
    p = safe(root, 'run/sync')
    p.mkdir(parents=True, exist_ok=True)
    return p


def git(root, *args, input=None, timeout=60, index=None, allowed_codes=(0,), commit_date=None):
    work = safe(root, '')
    gd = safe(root, '.git')
    if not work.is_dir() or (gd.exists() and not gd.is_dir()):
        raise Refused('.orch and .git must be real directories')
    if not gd.exists() and args[0] not in ('init', '--version', 'ls-files'):
        raise Refused('No state repository')  # never discover the outer repo
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('GIT_') or k in ('GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSL_CAINFO')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='', LC_ALL='C')
    env.pop('SSH_ASKPASS', None)
    if commit_date is not None:
        env.update(GIT_AUTHOR_DATE=commit_date, GIT_COMMITTER_DATE=commit_date)
    if index is not None:
        env['GIT_INDEX_FILE'] = str(Path(index).absolute())
    # Fresh private empty directory: never trust an existing hooks/attributes file.
    with tempfile.TemporaryDirectory(dir=local_dir(root)) as empty:
        attrs = Path(empty) / 'attributes'
        attrs.touch()
        opts = (*OPTIONS, f'core.hooksPath={empty}', f'core.attributesFile={attrs}')
        cmd = ['git', '-C', str(work), '--no-replace-objects', *[v for opt in opts for v in ('-c', opt)], *args]
        try:
            result = subprocess.run(cmd, input=input, capture_output=True, env=env, timeout=timeout, check=False)
            if result.returncode not in allowed_codes:
                raise Refused("Git operation failed")
            return result
        except (OSError, subprocess.SubprocessError) as e:
            raise Refused('Git operation failed') from e


def version_ok(root=None):
    if root is None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.orch').mkdir()
            return version_ok(root)
    m = re.search(rb'git version (\d+)\.(\d+)\.(\d+)', git(root, '--version').stdout)
    return bool(m and tuple(map(int, m.groups())) >= (2, 45, 1))


def check(root):
    gd = safe(root, '.git')
    if not gd.is_dir():
        raise Refused('.git must be a real directory')
    # lstat detects dangling links too; reject indirection before invoking git.
    for name in ('commondir', 'gitdir', 'config.worktree', 'objects/info/alternates', 'info/grafts'):
        path = gd / name
        parent = gd
        for part in Path(name).parts[:-1]:
            parent /= part
            if is_link(parent):
                raise Refused('unexpected git settings')
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        raise Refused('unexpected git settings')
    replace = gd / 'refs/replace'
    if is_link(gd / 'refs') or is_link(replace) or (replace.exists() and
            (not replace.is_dir() or any(replace.iterdir()))):
        raise Refused('unexpected git settings')
    if not version_ok(root):
        raise Refused('Update git to 2.45.1 or newer to use sync')
    common = os.fsdecode(git(root, 'rev-parse', '--git-common-dir').stdout).strip()
    if (Path(root) / '.orch' / common).resolve() != gd.resolve():
        raise Refused('unexpected git settings')
    safe(root, '.git/config')
    records = git(root, 'config', '--list', '--show-origin', '--show-scope', '-z').stdout.split(b'\0')
    if records.pop() != b'' or len(records) % 3:
        raise Refused('unexpected git settings')
    for scope, origin, record in zip(records[::3], records[1::3], records[2::3]):
        if scope not in (b'local', b'worktree'):
            continue
        if scope == b'worktree' or origin != b'file:.git/config':
            raise Refused('unexpected git settings')
        key, _, value = record.partition(b'\n')
        if not CONFIG.fullmatch(key.decode('utf-8')):
            raise Refused('unexpected git settings')
        if key == b'remote.origin.url':
            validate_url(value.decode('utf-8'))
    hooks = safe(root, '.git/hooks')
    if hooks.exists() and any(p.is_symlink() or not p.name.endswith('.sample') for p in hooks.iterdir()):
        raise Refused('unexpected hook, sync stopped')
    attrs = safe(root, '.git/info/attributes')
    if attrs.exists() and attrs.read_bytes().strip():
        raise Refused('unexpected git attributes')


def state(root):
    gd = safe(root, '.git')
    if gd.exists():
        check(root)
        return 'ready' if safe(root, '.git/orch-state').is_file() else 'needs-adoption'
    # Read-only discovery from .orch before init; no command ever changes the outer repo.
    if any((p / '.git').exists() for p in (Path(root), *Path(root).parents)):
        tracked = git(root, 'ls-files', '-z', '--', '.').stdout
        return 'needs-move' if tracked else 'new'
    return 'new'



def ensure(root):
    current = state(root)
    if current in ('new', 'ready'):
        from orch import tickets  # adopt this machine's own sessions BEFORE any remote ticket can arrive

        tickets.adopt_own_sessions(Path(root))
    if current == 'ready':
        return
    if current != 'new':
        raise Refused(f'{current}: explicit consent flow is not available yet')
    if not version_ok(root):
        raise Refused('Update git to 2.45.1 or newer to use sync')
    git(root, 'init', '-b', 'orch-state', '--template=')
    check(root)
    safe(root, '.git/info').mkdir(exist_ok=True)
    safe(root, '.git/info/exclude').write_text('\n'.join(NEVER_SYNCED) + '\n')
    safe(root, '.git/info/attributes').write_text('')
    safe(root, '.git/orch-state').write_text('1\n')


def recover(root):
    scratch = safe(root, 'run/tmp-sync')
    if scratch.exists():
        for p in scratch.iterdir():
            if is_link(p):
                if os.name == 'nt' and not p.is_symlink():
                    p.rmdir()  # remove the junction itself, never its target
                else:
                    p.unlink()
            elif not p.is_dir():
                p.unlink()
            else:
                shutil.rmtree(p)  # exact enumerated child; never follow a link


def validate_url(url):
    if not url or any(c.isspace() or ord(c) < 32 for c in url) or url.startswith(('-', 'ext::', 'fd::')):
        raise Refused('Unsupported remote address')
    parsed = urlsplit(url)
    if parsed.password is not None or (parsed.scheme in ('http', 'https') and '@' in parsed.netloc):
        raise Refused('Use your own git login, orch does not store passwords')
    if not (Path(url).is_absolute() or re.fullmatch(r'git@[A-Za-z0-9.-]+:[^\s]+', url)
            or (parsed.scheme in ('https', 'ssh') and parsed.hostname)
            or (parsed.scheme == 'file' and parsed.path.startswith('/') and parsed.netloc in ('', 'localhost'))):
        raise Refused('Unsupported remote address')


def set_remote(root, url):
    validate_url(url)
    check(root)
    git(root, 'config', '--local', '--replace-all', 'remote.origin.url', url)
    git(root, 'config', '--local', '--replace-all', 'remote.origin.fetch',
        '+refs/heads/orch-state:refs/remotes/origin/orch-state')
