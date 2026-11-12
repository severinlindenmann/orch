"""#591: needs-move only for tracked .orch files that are not team-owned (core TEAM_FILES); Move clears it."""

import io
import subprocess

from orch import cli as core_cli
from orch import humanproof

from orch_sync import repo


def git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def init(root):
    git(root, 'init', '-q')
    git(root, 'config', 'user.email', 't@example.invalid')
    git(root, 'config', 'user.name', 't')


def test_team_owned_gitignore_alone_is_not_needs_move(root):
    init(root)
    (root / '.orch' / '.gitignore').write_text('run/\n')
    git(root, 'add', '-f', '.orch/.gitignore')
    git(root, 'commit', '-qm', 'team')
    assert repo.state(root) == 'new'


def test_unknown_orch_file_is_needs_move(root):
    init(root)
    (root / '.orch' / 'unknown').write_text('personal')
    git(root, 'add', '-f', '.orch/unknown')
    assert repo.state(root) == 'needs-move'


def test_git_cannot_tell_stays_needs_move(root, monkeypatch):
    init(root)
    (root / '.orch' / 'unknown').write_text('personal')
    git(root, 'add', '-f', '.orch/unknown')

    def refused(*a, **k):
        raise repo.Refused('Git operation failed')

    monkeypatch.setattr(repo, 'git', refused)
    assert repo.state(root) == 'needs-move'


def test_move_with_extra_orch_files_clears_needs_move(root, monkeypatch):
    init(root)
    (root / '.orch' / 'config.toml').write_text('[workspace]\n')
    (root / '.orch' / '.gitignore').write_text('run/\n')
    (root / '.orch' / 'unknown').write_text('personal')
    (root / 'team.txt').write_text('team')
    git(root, 'add', '-f', '.orch', 'team.txt')
    git(root, 'commit', '-qm', 'oops')
    assert repo.state(root) == 'needs-move'
    key = humanproof.human_key(root)
    token = humanproof.mint(key, humanproof.new_payload('private.move', 'move', 'human:Pat'))
    monkeypatch.setattr('sys.stdin', io.StringIO(token + '\n'))
    monkeypatch.chdir(root)
    assert core_cli.main(['private', 'move', '--proof-stdin']) in (0, None)
    assert repo.state(root) == 'new'
    assert (root / '.orch' / 'unknown').is_file()
    out = subprocess.run(['git', '-C', str(root), 'ls-files', '--', '.orch'], capture_output=True, text=True, check=True).stdout
    assert out.split() == ['.orch/.gitignore']  # the team-owned file stays tracked
