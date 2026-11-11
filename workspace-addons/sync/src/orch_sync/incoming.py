"""Pure incoming verdicts: inspect objects, never check out or apply them."""
import json
import math
from dataclasses import dataclass

from . import paths, repo, scan

MB = 1_000_000


@dataclass(frozen=True)
class Problem:
    path: str
    code: str
    message: str


def strict_load(data):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out or k == '__proto__':
                raise ValueError('duplicate or unsafe key')
            out[k] = v
        return out

    value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs)
    stack = [(value, 1)]
    while stack:
        v, depth = stack.pop()
        if isinstance(v, (dict, list)):
            if depth > 32:
                raise ValueError('JSON nesting exceeds 32')
            stack.extend((x, depth + 1) for x in (list(v) + list(v.values()) if isinstance(v, dict) else v))
        elif isinstance(v, str) and len(v.encode('utf-8')) > MB:
            raise ValueError('JSON string too long')
        elif isinstance(v, float) and not math.isfinite(v):
            raise ValueError('non-finite number')
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')  # noqa: TRY004 - malformed document
    return value


def tree(root, ref):
    raw = repo.git(root, 'ls-tree', '-r', '-z', ref).stdout
    return [(*entry.split(b'\t', 1)[0].decode('ascii').split(),
             entry.split(b'\t', 1)[1].decode('utf-8')) for entry in raw.split(b'\0') if entry]


def check(root, ref='origin/orch-state', *, base='HEAD') -> list[Problem]:
    # The step supplies the common ancestor: a new local-only ticket is not a remote deletion.
    problems = []
    try:
        repo.check(root)
        if ref.startswith('-') or not ref or any(c.isspace() for c in ref):
            raise ValueError('Invalid ref')
        # Pin once so tree, sizes and diff all describe the same commit.
        tip = repo.git(root, 'rev-parse', '--verify', ref + '^{commit}').stdout.decode().strip()
        head = (repo.git(root, 'rev-parse', '--verify', base).stdout if base else
                repo.git(root, 'hash-object', '-w', '-t', 'tree', '--stdin', input=b'').stdout).decode().strip()
        entries, old = tree(root, tip), tree(root, head)
        if len(entries) > 5000:
            return [Problem('', 'size', 'Too many files')]
        seen = {}
        for mode, kind, oid, path in entries:
            if not paths.allowed(path) or mode != '100644' or kind != 'blob':
                problems.append(Problem(path, 'path', 'The remote has files orch does not accept'))
            parts = path.split('/')
            for i in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:i])
                key = prefix.casefold()
                if key in seen and seen[key] != prefix:
                    problems.append(Problem(path, 'path', 'Case-fold collision'))
                seen[key] = prefix
        if problems:
            return problems
        sizes = repo.git(root, 'cat-file', '--batch-check',
                         input=''.join(f'{e[2]}\n' for e in entries).encode()).stdout.splitlines()
        total = 0
        if len(sizes) != len(entries):
            raise ValueError('Missing object sizes')
        for entry, row in zip(entries, sizes):
            _, _, oid, path = entry
            got, kind, length = row.decode().split()
            size = int(length)
            if got != oid or kind != 'blob' or size < 0:
                raise ValueError('Invalid object')
            total += size
            if size > (MB if paths.TICKET.fullmatch(path) else 25 * MB):
                problems.append(Problem(path, 'size', 'File exceeds sync limit'))
        if total > 500 * MB:
            problems.append(Problem('', 'size', 'Tree exceeds sync limit'))
        if problems:
            return problems
        diff = repo.git(root, 'diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z',
                        '--no-renames', f'{head}..{tip}', '--').stdout.split(b'\0')
        deleted = []
        for status, name in zip(diff[0::2], diff[1::2]):
            path = name.decode('utf-8')
            if status == b'D':
                if paths.TICKET.fullmatch(path):
                    problems.append(Problem(path, 'ticket-deletion', 'Incoming ticket deletion refused'))
                elif paths.ARTIFACT.fullmatch(path):
                    deleted.append(path)
        count = sum(bool(paths.ARTIFACT.fullmatch(e[3])) for e in old)
        if len(deleted) > 5 or len(deleted) > count * .2:
            problems.append(Problem('', 'needs-confirm', f'Many files were removed ({len(deleted)}). Apply?'))
        old_oids = {e[3]: e[2] for e in old}
        for _, _, oid, path in entries:
            data = repo.git(root, 'cat-file', 'blob', oid).stdout
            problems.extend(Problem(path, f.code, f.rule) for f in scan.scan_blob(path, data))
            if not (paths.TICKET.fullmatch(path) or path == 'ticket-counter.json'):
                continue
            doc = strict_load(data)
            if doc.get('general') is True:
                problems.append(Problem(path, 'private', 'General ticket stays local'))
            if paths.TICKET.fullmatch(path):
                previous = strict_load(repo.git(root, 'cat-file', 'blob', old_oids[path]).stdout) \
                    if path in old_oids else {}
                if doc.get('ext', {}) != previous.get('ext', {}):
                    problems.append(Problem(path, 'held-ext', 'Extension changes need local approval'))
    except (repo.Refused, ValueError, OSError, RecursionError) as e:
        problems.append(Problem('', 'invalid', 'Incoming state could not be validated: ' + type(e).__name__))
    return problems
