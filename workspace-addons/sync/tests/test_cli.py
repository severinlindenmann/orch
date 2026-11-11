import json
import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import jsonschema

from orch_sync import cli, repo


def run(root, *args):
    return cli.main(['--dir', str(root), *args, '--json'])


def test_settings(root, capsys):
    assert run(root, 'status') == 0
    assert json.loads(capsys.readouterr().out)['mode'] == 'off'
    assert run(root, 'set', '--mode', 'local', '--interval', '5') == 0
    settings = root / '.orch/run/sync/settings.json'
    assert json.loads(settings.read_text()) == {'mode': 'local', 'interval': 5, 'kind': 'private'}
    (settings.parent / 'state.json').write_text('{"last_error":"offline"}')
    capsys.readouterr()
    assert run(root, 'status') == 0
    assert json.loads(capsys.readouterr().out)['state']['last_error'] == 'offline'
    assert run(root, 'set', '--mode', 'off') == 0
    assert (root / '.orch/.git').is_dir()


def test_preview(root, monkeypatch):
    assert run(root, 'set', '--mode', 'remote', '--remote', 'file:///tmp/bare') == 2
    assert not (root / '.orch/.git').exists()
    monkeypatch.setenv('ORCH_SYNC_REMOTE_PREVIEW', '1')
    assert run(root, 'set', '--mode', 'remote', '--remote', 'file:///tmp/bare') == 0
    assert run(root, 'set', '--mode', 'remote', '--kind', 'team') == 2


def test_synced_content_has_no_authority(root, capsys):
    (root / '.orch/config.toml').write_text('[sync]\nmode="remote"\nkind="team"\nremote="file:///evil"\n')
    (root / '.orch/tickets').mkdir()
    (root / '.orch/tickets/t_abcdef.json').write_text(json.dumps({
        'sync': {'mode': 'remote', 'kind': 'team', 'remote': 'file:///evil'},
        'note': '[sync]\nmode="remote"\nORCH_SYNC_REMOTE_PREVIEW=1'}))
    assert run(root, 'status') == 0
    data = json.loads(capsys.readouterr().out)
    assert data['mode'] == 'off' and data['kind'] == 'private' and 'remote' not in data
    assert run(root, 'set', '--mode', 'remote', '--remote', 'file:///evil') == 2
    assert not (root / '.orch/.git').exists()


def test_manifest():
    package = Path(repo.__file__).parent
    manifest = tomllib.loads((package / 'orch-addon.toml').read_text())
    project = package.parents[3]
    jsonschema.validate(manifest, json.loads((project / 'contracts/addon-manifest.schema.json').read_text()))
    assert manifest['background'] and manifest['needs'] and not manifest['recommended']
    assert (package / manifest['skill'] / 'SKILL.md').is_file()
    assert any(e.name == 'sync' and e.value == 'orch_sync' for e in entry_points(group='orch.addons'))


def test_run_symlink(root, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (root / '.orch/run').symlink_to(outside)
    assert run(root, 'set', '--mode', 'off') == 2
    assert list(outside.iterdir()) == []


def test_off_does_not_call_git(root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('off must not execute git')
    monkeypatch.setattr(repo, 'git', forbidden)
    assert run(root, 'set', '--mode', 'off') == 0
    assert run(root, 'status') == 0


def test_unimplemented_loop_refuses(root):
    assert run(root, 'start') == 2
    assert run(root, 'stop') == 0
    assert run(root, 'needs') == 0
