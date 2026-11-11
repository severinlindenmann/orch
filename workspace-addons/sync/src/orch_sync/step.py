"""One conservative sync transaction. Only repo.git executes git; live writes are gated."""
import contextlib
import hashlib
import json
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from orch import procs, syncgate, tickets
from orch.errors import Refused as CoreRefused

from . import cli, incoming, merge, paths, repo, scan

MB = 1_000_000


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False) + '\n').encode()


def write(root, relative, data):
    p = repo.safe(root, relative)
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=p.parent, delete=False) as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        syncgate.replace(f.name, p)
    finally:
        Path(f.name).unlink(missing_ok=True)


def oid(root, ref):
    r = repo.git(root, 'rev-parse', '--verify', ref, allowed_codes=(0, 128))
    return r.stdout.decode().strip() if r.returncode == 0 else None


def entries(root, ref):
    return {p: (mode, obj) for mode, kind, obj, p in incoming.tree(root, ref)} if ref else {}


def blob(root, entry):
    return repo.git(root, 'cat-file', 'blob', entry[1]).stdout if entry else None


def put(root, index, path, data):
    obj = repo.git(root, 'hash-object', '-w', '--stdin', input=data).stdout.decode().strip()
    repo.git(root, 'update-index', '--add', '--cacheinfo', f'100644,{obj},{path}', index=index)


def document(path, data):
    try:
        doc = incoming.strict_load(data)
    except (ValueError, RecursionError):
        raise repo.Refused(f'Document has a problem: {path}') from None
    if paths.TICKET.fullmatch(path):
        if not isinstance(doc.get('ext', {}), dict):
            raise repo.Refused(f'Ticket has a problem: {path}')
        checks = [('ticket', doc)] + [(f'addons/{name}/ext', value)
                                     for name, value in doc.get('ext', {}).items()
                                     if name in ('automation', 'focus')]
        for name, value in checks:
            schema = Path(__file__).parent / 'schemas' / f'{name}.schema.json'
            if not schema.exists():  # the wheel includes these authoritative contracts
                schema = Path(__file__).resolve().parents[4] / 'contracts' / f'{name}.schema.json'
            validator = Draft202012Validator(json.loads(schema.read_text()), format_checker=FormatChecker())
            if not validator.is_valid(value) or doc.get('id') != Path(path).stem:
                raise repo.Refused(f'Ticket has a problem: {path}')
    return doc


def validate_tree(root, tree):
    seen, total, folders, keys = {}, 0, {}, {}
    rows = entries(root, tree)
    if len(rows) > 5000:
        raise repo.Refused('Too many files')
    for path, entry in rows.items():
        if not paths.allowed(path) or entry[0] != '100644':
            raise repo.Refused('Tree contains a refused path or file mode')
        for i in range(1, len(path.split('/')) + 1):
            prefix = '/'.join(path.split('/')[:i])
            if seen.setdefault(prefix.casefold(), prefix) != prefix:
                raise repo.Refused('Case-fold collision')
        size = int(repo.git(root, 'cat-file', '-s', entry[1]).stdout)
        if size > (MB if paths.TICKET.fullmatch(path) else 25 * MB):
            raise repo.Refused(f'File exceeds sync limit: {path}')
        total += size
        if paths.ARTIFACT.fullmatch(path):
            folder = '/'.join(path.split('/')[:3])
            count, used = folders.get(folder, (0, 0))
            folders[folder] = count + 1, used + size
        data = blob(root, entry)
        findings = scan.scan_blob(path, data)
        if findings:
            raise repo.Refused(f'Not synced: {path}: {findings[0].code}')
        if paths.TICKET.fullmatch(path) or path == 'ticket-counter.json':
            doc = document(path, data)
            if doc.get('general') is True:
                raise repo.Refused('General ticket stays local')
            if paths.TICKET.fullmatch(path) and doc.get('key') and keys.setdefault(doc['key'], path) != path:
                raise repo.Refused('Ticket key clash needs a person')
    for path in rows:
        if paths.ARTIFACT.fullmatch(path):
            owner = '/'.join(path.split('/')[:2]) + '.json'
            if owner not in rows:
                raise repo.Refused(f'Artifact has no ticket: {path}')
            doc = document(owner, blob(root, rows[owner]))
            if doc.get('general') is True:
                raise repo.Refused('General ticket stays local')
    if total > 500 * MB or any(n > 200 or size > 200 * MB for n, size in folders.values()):
        raise repo.Refused('Too much to sync')


def deletions(old, new):
    gone = [p for p in old.keys() - new.keys() if paths.ARTIFACT.fullmatch(p)]
    folders = {p.split('/')[1] for p in gone}
    too_many = any(
        (count := sum(paths.ARTIFACT.fullmatch(p) is not None and p.split('/')[1] == tid for p in old)) > 5
        and sum(p.split('/')[1] == tid for p in gone) > count * .2
        for tid in folders
    )
    if len(gone) > 5 or too_many:
        raise repo.Refused(f'Many files were removed ({len(gone)}). Apply?')


def stage(root, head, index, state):
    old = entries(root, head)
    repo.git(root, 'read-tree', head or '--empty')
    repo.git(root, 'read-tree', head or '--empty', index=index)
    names = set(old)
    work = repo.safe(root, '')
    for parent, dirs, files in os.walk(repo.safe(root, 'tickets'), followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        names.update((Path(parent) / f).relative_to(work).as_posix() for f in files)
    names.add('ticket-counter.json')
    generals, preserved = set(), set()
    for path in sorted(names):
        if any(path.startswith(f'tickets/{tid}/') for tid in preserved):
            continue  # The index already contains HEAD's artifacts.
        if not paths.allowed(path) or any(path.startswith(f'tickets/{tid}/') for tid in generals):
            if path in old:
                repo.git(root, 'update-index', '--force-remove', '--', path, index=index)
            continue
        tid = path.split('/')[1].removesuffix('.json') if path.startswith('tickets/') else 'key'
        with tickets.sync_apply(root, tid):
            try:
                try:
                    p = repo.safe(root, path)
                except repo.Refused:
                    raise ValueError('Link stays local') from None
                info = p.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('Not a regular single-link file')
                if info.st_size > 25 * MB:
                    raise ValueError('File exceeds 25 MB')
                if paths.TICKET.fullmatch(path) or path == 'ticket-counter.json':
                    try:
                        data = p.read_bytes()
                        doc = incoming.strict_load(data)
                        if doc.get('general') is not True:
                            if paths.TICKET.fullmatch(path) and info.st_size > MB:
                                raise ValueError('Ticket exceeds 1 MB')
                            doc = document(path, data)
                    except (ValueError, RecursionError):
                        raise ValueError('Ticket has a problem') from None
                    if doc.get('general') is True:
                        raise ValueError('General ticket stays local')
                repo.git(root, 'add', '-f', '--', ':(literal)' + path, index=index)
            except FileNotFoundError:
                if paths.TICKET.fullmatch(path):
                    (preserved if path in old else generals).add(Path(path).stem)
                    state['skipped'].append(f'Ticket {Path(path).stem} has a problem and was not synced')
                if path in old:
                    if paths.TICKET.fullmatch(path):
                        write(root, path, blob(root, old[path]))
                        state['skipped'].append(f'A ticket file is missing: {path}. Restored it.')
                    else:
                        repo.git(root, 'update-index', '--force-remove', '--', path, index=index)
            except (ValueError, OSError) as e:
                if paths.TICKET.fullmatch(path):
                    (preserved if path in old else generals).add(Path(path).stem)
                    state['skipped'].append(f'Ticket {Path(path).stem} has a problem and was not synced: {e}')
                elif isinstance(e, repo.Refused):
                    raise
                else:
                    state['skipped'].append(f'{path}: {e}')
    # Purge only excluded folders whose ticket JSON was never tracked in HEAD.
    excluded = {p for p in names if any(
        p == f'tickets/{tid}.json' or p.startswith(f'tickets/{tid}/') for tid in generals
    )}
    for path in sorted(excluded & old.keys()):
        repo.git(root, 'update-index', '--force-remove', '--', path, index=index)
        repo.git(root, 'update-index', '--force-remove', '--', path)
    tree = repo.git(root, 'write-tree', index=index).stdout.decode().strip()
    deletions({p: e for p, e in old.items() if p not in excluded}, entries(root, tree))
    validate_tree(root, tree)  # every byte, including unchanged staged blobs
    return tree


def commit(root, tree, parents, now):
    args = [v for parent in parents if parent for v in ('-p', parent)]
    return repo.git(root, '-c', 'user.name=orch', '-c', 'user.email=orch@localhost',
                    'commit-tree', tree, *args, input=f'orch sync {now}\n'.encode(), commit_date=now).stdout.decode().strip()


def held_ticket(root, path, doc, local, remote):
    # No manifest inert declaration is shipped yet: default every add-on to non-inert.
    ext, theirs = local.get('ext', {}), remote.get('ext', {})
    for addon in set(ext) | set(theirs):
        if ext.get(addon) != theirs.get(addon):
            block = {'ticket': Path(path).stem, 'addon': addon, 'value': theirs.get(addon)}
            raw = encoded(block)
            name = f"{Path(path).stem}-{hashlib.sha256(raw).hexdigest()}.json"
            write(root, 'run/sync/held/' + name, raw)
    if 'ext' in local:
        doc['ext'] = ext
    else:
        doc.pop('ext', None)
    if 'sessions' in local:
        doc['sessions'] = local['sessions']
    else:
        doc.pop('sessions', None)
    return doc


def merged_tree(root, head, remote, index, now):
    result = repo.git(root, 'merge-tree', '--write-tree', '--no-messages', '-z',
                      '--allow-unrelated-histories', head, remote, allowed_codes=(0, 1))
    fields = result.stdout.split(b'\0')
    tree = fields[0].decode()
    conflicts = {}
    for field in fields[1:]:
        if not field:
            continue
        meta, path = field.split(b'\t', 1)
        mode, obj, stage_no = meta.decode().split()
        conflicts.setdefault(path.decode(), {})[int(stage_no)] = (mode, obj)
    if any(not paths.TICKET.fullmatch(p) and p != 'ticket-counter.json' for p in conflicts):
        raise repo.Refused('Conflicting artifact needs a person')
    repo.git(root, 'read-tree', tree, index=index)
    base_result = repo.git(root, 'merge-base', head, remote, allowed_codes=(0, 1))
    base = entries(root, base_result.stdout.decode().strip() or None)
    ours, theirs = entries(root, head), entries(root, remote)
    for path in sorted(theirs):
        if not (paths.TICKET.fullmatch(path) or path == 'ticket-counter.json'):
            continue
        if theirs[path] == base.get(path) or theirs[path] == ours.get(path):
            continue
        versions = conflicts.get(path, {1: base.get(path), 2: ours.get(path), 3: theirs[path]})
        b, a, t = [incoming.strict_load(blob(root, versions.get(n)) or b'{}') for n in (1, 2, 3)]
        if path == 'ticket-counter.json':
            doc = merge.merge_counter(b, a, t)
        else:
            doc = merge.merge_ticket(b or None, t, a or t, now=now)
            if doc is None:
                raise repo.Refused(f'Ticket cannot be merged: {path}')
            doc = held_ticket(root, path, doc, a, t)
        document(path, encoded(doc))
        put(root, index, path, encoded(doc))
    tree = repo.git(root, 'write-tree', index=index).stdout.decode().strip()
    validate_tree(root, tree)
    deletions(ours, entries(root, tree))
    return tree


def apply(root, old, new, state):
    before, after = entries(root, old), entries(root, new)
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) == after.get(path):
            continue
        tid = path.split('/')[1].removesuffix('.json') if path.startswith('tickets/') else 'key'
        with tickets.sync_apply(root, tid):
            p = repo.safe(root, path)
            previous, data = blob(root, before.get(path)), blob(root, after.get(path))
            if p.exists() and (not stat.S_ISREG(p.lstat().st_mode) or p.stat().st_nlink != 1):
                raise repo.Refused(f'{path}: busy')
            current = p.read_bytes() if p.exists() else None
            if current == data:
                continue  # an interrupted apply already replaced this path
            if current != previous or (p.exists() and not p.is_file()):
                state['skipped'].append(f'{path}: busy')
                raise repo.Refused(f'{path}: busy')
            try:
                if data is None:
                    p.unlink(missing_ok=True)
                else:
                    write(root, path, data)
            except PermissionError:
                raise repo.Refused(f'{path}: busy') from None
    repo.git(root, 'update-ref', 'refs/heads/orch-state', new, old)
    repo.git(root, 'read-tree', new)
    repo.git(root, 'update-index', '--refresh', allowed_codes=(0, 1))


@contextlib.contextmanager
def step_lock(root):
    p = repo.safe(root, 'run/sync/step.lock')
    with syncgate.hold(root, 'step-lock'):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not procs.owner_dead(p.read_text()):
                raise repo.Refused('Sync is already running') from None
            p.unlink()
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(procs.own_token())
    try:
        yield
    finally:
        p.unlink()


def _run(root, reason, now, remote_allowed):
    state = cli.read(root, 'state') | {'last_error': None, 'skipped': [], 'reason': reason}
    try:
        repo.local_dir(root)
        settings = cli.DEFAULTS | cli.read(root, 'settings')
        if settings['kind'] != 'private':
            raise repo.Refused('Team sync is not available yet')
        if settings['mode'] == 'off':
            return state
        network = settings['mode'] == 'remote'
        if network and not remote_allowed:
            raise repo.Refused('Remote sync is preview-only')
        repo.ensure(root)
        repo.recover(root)
        for attempt in range(2):
            head, remote, offline = oid(root, 'HEAD'), None, False
            url = settings.get('remote')
            if network:
                if not url:
                    raise repo.Refused('A remote address is required')
                repo.set_remote(root, url)
                try:
                    repo.git(root, 'fetch', '--no-tags', '--prune', 'origin',
                             '+refs/heads/*:refs/remotes/origin/*', timeout=60)
                except repo.Refused:
                    offline = True
                if not offline:
                    remote = oid(root, 'refs/remotes/origin/orch-state')
                    last = state.get('remote_sha') if state.get('remote_url') == url else None
                    if last and (not remote or repo.git(root, 'merge-base', '--is-ancestor', last,
                                                       remote, allowed_codes=(0, 1)).returncode):
                        raise repo.Refused('The remote history was rewritten')
                    if remote:
                        common = repo.git(root, 'merge-base', head, remote, allowed_codes=(0, 1)) \
                            if head else None
                        base = (common.stdout.decode().strip() or None) if common else None
                        result = incoming.check(root, remote, base=base)
                        problems = [p for p in result.problems if p.code != 'held-ext']
                        if problems:
                            raise repo.Refused(problems[0].message)
                        if not result.commit:
                            raise repo.Refused('Incoming state has no checked commit')
                        remote = result.commit
                        validate_tree(root, remote)
            scratch_root = repo.safe(root, 'run/tmp-sync')
            scratch_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=scratch_root) as scratch:
                index = Path(scratch) / 'index'
                with syncgate.hold(root):
                    pending = cli.read(root, 'pending')
                    if pending and not offline:
                        if pending['old'] == head and pending.get('url') == url and pending.get('remote') == remote:
                            validate_tree(root, pending['new'])
                            apply(root, head, pending['new'], state)
                            head = pending['new']
                        repo.safe(root, 'run/sync/pending.json').unlink()
                    tree = stage(root, head, index, state)
                    if not head or tree != oid(root, head + '^{tree}'):
                        new = commit(root, tree, [head], now)
                        repo.git(root, 'update-ref', 'refs/heads/orch-state', new, head or '0' * 40)
                        head = new
                    repo.git(root, 'read-tree', head)
                if network and not offline:
                    first = state.get('remote_url') != url
                    parent = commit(root, tree, [], now) if first else head
                    if remote and remote != parent:
                        tree = merged_tree(root, parent, remote, index, now)
                        new = commit(root, tree, [parent, remote], now)
                    else:
                        new = parent
                    if new != head:
                        write(root, 'run/sync/pending.json', encoded({'old': head, 'new': new, 'url': url, 'remote': remote}))
                        with syncgate.hold(root):
                            apply(root, head, new, state)
                        repo.safe(root, 'run/sync/pending.json').unlink()
                        head = new
                if not network:
                    break
                if offline:
                    raise repo.Refused('offline')
                # A push transfers history, not just the current tree. Validate every
                # outgoing tree, scanning full blob bytes (including unchanged blobs).
                revisions = [head] + (['--not', remote] if remote else [])
                for outgoing in repo.git(root, 'rev-list', *revisions).stdout.decode().splitlines():
                    validate_tree(root, outgoing)
                try:
                    pushed = repo.git(root, 'push', 'origin', f'{head}:refs/heads/orch-state', timeout=60, allowed_codes=(0, 1))
                except repo.Refused:
                    raise repo.Refused('offline') from None
                if pushed.returncode == 0:
                    state.update(remote_sha=head, remote_url=url)
                    break
                if attempt or b'[rejected]' not in pushed.stderr:
                    raise repo.Refused('offline')
        state['last_ok'] = now
    except (ValueError, OSError, CoreRefused) as e:
        state['last_error'] = str(e)
        if 'busy' in str(e):
            repo.safe(root, 'run/sync/pending.json').unlink(missing_ok=True)
    head, remote = oid(root, 'HEAD') if repo.safe(root, '.git').is_dir() else None, None
    if head:
        remote = oid(root, 'refs/remotes/origin/orch-state')
    counts = repo.git(root, 'rev-list', '--left-right', '--count', f'{head}...{remote}').stdout.split() \
        if head and remote else [int(repo.git(root, 'rev-list', '--count', head).stdout) if head else 0, 0]
    state.update(ahead=int(counts[0]), behind=int(counts[1]))
    write(root, 'run/sync/state.json', encoded(state))
    return state


def run_once(root, reason, *, now=None):
    remote_allowed = cli.remote_allowed()
    root = Path(root)
    now = now or datetime.now(UTC).isoformat().replace('+00:00', 'Z')
    try:
        repo.local_dir(root)
        with step_lock(root):
            return _run(root, reason, now, remote_allowed)
    except (ValueError, OSError, CoreRefused) as e:
        # A competing step owns state.json too; do not overwrite its result.
        return {'last_error': str(e), 'skipped': [], 'reason': reason}
