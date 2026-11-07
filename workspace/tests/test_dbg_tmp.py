import subprocess
from test_relay_client import *
def test_x(proj, run, rel):
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    print(connect(run, rel))
    print((proj/".git/info/exclude").read_text()[-600:])
    print(list((proj/".orch").iterdir()))
    assert 0
