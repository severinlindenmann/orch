"""Read-only bridge to the installed orch CLI."""
import json
import os
import subprocess


def call(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    try:
        p = subprocess.run([env.get('ORCH_BIN') or 'orch', *args, '--json'], cwd=root,
                           env=env, capture_output=True, timeout=60, check=True)
        return json.loads(p.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
