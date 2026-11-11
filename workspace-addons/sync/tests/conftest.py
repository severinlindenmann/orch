import pytest

from orch_sync import repo


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    for key, value in [('HOME', home), ('XDG_CONFIG_HOME', home / 'xdg'),
                       ('GIT_CONFIG_GLOBAL', home / 'gitconfig')]:
        monkeypatch.setenv(key, str(value))
    monkeypatch.delenv('ORCH_SYNC_REMOTE_PREVIEW', raising=False)


@pytest.fixture
def root(tmp_path):
    root = tmp_path / 'workspace'
    (root / '.orch').mkdir(parents=True)
    return root


@pytest.fixture
def ready(root):
    repo.ensure(root)
    repo.git(root, 'config', 'user.name', 'Test')
    repo.git(root, 'config', 'user.email', 'test@example.invalid')
    repo.git(root, 'commit', '--allow-empty', '-m', 'base')
    return root
