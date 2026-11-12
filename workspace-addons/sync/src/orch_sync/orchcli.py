"""Bridge to the installed orch CLI and the one place the loop process is started (no `subprocess` elsewhere)."""
import json
import os
import subprocess
import sys


def call(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    try:
        p = subprocess.run([env.get('ORCH_BIN') or 'orch', *args, '--json'], cwd=root,
                           env=env, capture_output=True, timeout=60, check=True)
        return json.loads(p.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def is_active(root):
    """Is the sync add-on turned on here? None = could not find out (keep running), like automation."""
    data = call(root, 'addon', 'list')
    if not isinstance(data, list):
        return None
    return any(isinstance(a, dict) and a.get('name') == 'sync' and bool(a.get('active')) for a in data)


def spawn(root, args, out, env):
    """`python -P -m orch_sync <args>` in the background (-P: the workspace folder is never on the import path)."""
    from orch.procs import background_popen_kwargs

    return subprocess.Popen([sys.executable, '-P', '-m', 'orch_sync', *args], cwd=root, stdout=out,
                            stderr=subprocess.STDOUT, env=env, **background_popen_kwargs())


def command(pid):
    """The command line of pid (POSIX, from ps); '' on Windows or when unknown."""
    if os.name == 'nt':
        return ''
    try:
        r = subprocess.run(['ps', '-ww', '-o', 'command=', '-p', str(pid)], capture_output=True, text=True,
                           timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.strip()
