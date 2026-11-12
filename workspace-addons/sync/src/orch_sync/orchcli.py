"""Bridge to the orch core and the one place the loop process is started (no `subprocess` elsewhere).

The core is this Python's own orch (`python -I -P -m orch`, procs.orch_python_argv), like the dashboard and focus
call it: never ORCH_BIN and never a name looked up on PATH or in the workspace folder."""
import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent  # the loop's working folder: the add-on's own, never the workspace
_run, _popen = subprocess.run, subprocess.Popen  # module-local seams: tests never patch the global ones


def call(root, *args):
    from orch.procs import orch_python_argv

    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_') and k != 'ORCH_BIN'}
    try:
        p = _run(orch_python_argv(*args, '--json'), cwd=root, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=60, check=True)
        return json.loads(p.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def is_active(root):
    """Is the sync add-on turned on here? None = could not find out (keep running), like automation."""
    data = call(root, 'addon', 'list')
    if not isinstance(data, list):
        return None
    return any(isinstance(a, dict) and a.get('name') == 'sync' and bool(a.get('active')) for a in data)


def spawn(args, out, env):
    """`<this python> -P -m orch_sync <args>` in the background, in the add-on's own folder (-P: no working
    folder on the import path). The interpreter path must be absolute: nothing is looked up."""
    from orch.procs import background_popen_kwargs

    exe = sys.executable
    if not exe or not os.path.isabs(exe):
        raise OSError('This Python does not know its own path; sync cannot start in the background')
    return _popen([exe, '-P', '-m', 'orch_sync', *args], cwd=HOME, stdout=out,
                            stderr=subprocess.STDOUT, env=env, **background_popen_kwargs())
