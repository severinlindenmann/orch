import pytest

from orch_sync import repo


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    from orch import addons, humanproof

    # The suite runs as a TEST install (the same core check the guarded home uses): local bare remotes are
    # allowed there, inspected before every push/fetch. Tests of a normal install use `normal_install`.
    monkeypatch.setattr(humanproof, 'install_kind', lambda: 'test')
    monkeypatch.setattr(addons, "real_home", lambda: home)
    monkeypatch.setattr(addons, "discover", dict)
    for key, value in [('HOME', home), ('XDG_CONFIG_HOME', home / 'xdg'),
                       ('GIT_CONFIG_GLOBAL', home / 'gitconfig')]:
        monkeypatch.setenv(key, str(value))
    monkeypatch.delenv('ORCH_SYNC_REMOTE_PREVIEW', raising=False)


@pytest.fixture
def normal_install(monkeypatch):
    """A real (normal) install: sync accepts only https and ssh remotes."""
    from orch import humanproof

    monkeypatch.setattr(humanproof, 'install_kind', lambda: 'normal')


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
