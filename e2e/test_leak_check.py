"""The e2e LEAK check finds an add-on process by the folder it was started for, also when that folder is outside the
run's temp root or already deleted (the Factory watchers that stayed for days). Run: python3 -m unittest e2e/test_leak_check.py"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


class LeakCheck(unittest.TestCase):
    def test_finds_and_ends_a_watcher_of_a_deleted_folder(self):
        with tempfile.TemporaryDirectory() as mods, tempfile.TemporaryDirectory() as other:
            Path(mods, "orch_fakewatch.py").write_text("import time\ntime.sleep(60)\n")
            ws = Path(other) / "e2e-a18-1" / "ws"
            ws.mkdir(parents=True)
            p = subprocess.Popen([sys.executable, "-m", "orch_fakewatch", "--dir", str(ws), "watch"],
                                 env={**os.environ, "PYTHONPATH": mods}, cwd=mods)
            try:
                time.sleep(0.5)
                self.assertEqual([], [x for x, _ in lib.orch_processes_under([Path(other) / "e2e-zzz-9"])])
                found = [x for x, _ in lib.orch_processes_under([Path(other) / "e2e-a18-1"])]
                self.assertEqual([p.pid], found)
                lib.end_processes(found)
                self.assertIsNotNone(p.wait(5))
                self.assertEqual([], [x for x, _ in lib.orch_processes_under([Path(other) / "e2e-a18-1"])])
            finally:
                p.kill()
                p.wait()


if __name__ == "__main__":
    unittest.main()
