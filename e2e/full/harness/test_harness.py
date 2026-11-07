"""T0 for the harness itself: python3 -m unittest e2e/full/harness/test_harness.py (stdlib only, no servers)."""
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import findings  # noqa: E402
import lane  # noqa: E402
import receiver  # noqa: E402
import report  # noqa: E402


class HarnessTests(unittest.TestCase):
    def test_lane_step_and_probe(self):
        with tempfile.TemporaryDirectory() as d:
            L = lane.Lane("T", "t", Path(d))
            L.step("T01", "ok", lambda st: "fine")
            L.step("T02", "bad", lambda st: 1 / 0)
            L.step("T03", "skip", lambda st: (_ for _ in ()).throw(lane.Skipped("later")))
            L.probe("p", "probe", [1, 2, 3, 10], 2, 5)
            r = L.save()
            self.assertEqual([s["status"] for s in r["steps"]], ["pass", "fail", "skipped"])
            self.assertEqual(r["probes"]["p"]["median"], 2.5)
            self.assertTrue((Path(d) / "result.json").exists())

    def test_findings_have_now_and_proposal(self):
        res = {"lane": "A", "steps": [{"id": "A01", "name": "n", "status": "fail", "error": "boom", "expect": "x",
                                       "lint": [{"rule": "vpn-product", "text": "NetBird", "where": "over NetBird"}],
                                       "shots": [{"vp": 390, "file": "shots/a.png", "hscroll": True}]}],
               "coverage": {"found": 10, "clicked": 5, "percent": 50, "uncovered": ["a|b"]},
               "probes": {"p": {"id": "p", "name": "slow", "median": 5, "p95": 9, "target": 2, "hard": 4, "unit": "s", "samples": [5]}}}
        fs = findings.from_lane(res, "A", timing_fail=True)
        kinds = {f["kind"] for f in fs}
        self.assertTrue({"step-failed", "wording", "layout", "coverage", "timing"} <= kinds)
        for f in fs:
            self.assertTrue(f["now"] and f["proposal"], f)
        self.assertEqual([f for f in fs if f["kind"] == "timing"][0]["severity"], "functional")
        fs2 = findings.from_lane(res, "A", timing_fail=False)
        self.assertEqual([f for f in fs2 if f["kind"] == "timing"][0]["severity"], "ux")

    def test_receiver_records_and_fails_first(self):
        r = receiver.Receiver(fail_first=1)
        r.start()
        try:
            for _ in range(2):
                try:
                    urllib.request.urlopen(urllib.request.Request(r.url + "/push", data=b'{"a":1}', method="POST"))
                except Exception:  # noqa: BLE001
                    pass
            self.assertTrue(r.wait(2, 3))
            self.assertEqual(json.loads(r.got[0]["body"]), {"a": 1})
        finally:
            r.stop()

    def test_run_sh_keeps_an_argument_with_spaces_as_one_word(self):
        import os
        import subprocess
        run_sh = Path(__file__).resolve().parents[1] / "run.sh"
        r = subprocess.run(["sh", str(run_sh), "--full", "--build-label", "TF 261107.140550", "--phone"], capture_output=True, text=True,
                           env={**os.environ, "E2E_FULL_LOCKED": "1", "E2E_FULL_ARGS_ONLY": "1"})
        self.assertEqual(r.stdout.splitlines(), ["mode=full", "arg=--build-label", "arg=TF 261107.140550", "arg=--phone"])

    def test_report_header_shows_build_label(self):
        with tempfile.TemporaryDirectory() as d:
            run = {"sha": "abcdef123456", "mode": "full", "started": "now", "elapsed": "1 min", "n": 1, "build_label": "TF 42"}
            h = report.render(run, [], [], {"found": 0, "clicked": 0, "percent": 0}, Path(d)).read_text()
            self.assertIn("build TF 42", h)

    def test_report_renders_findings_first(self):
        with tempfile.TemporaryDirectory() as d:
            run = {"sha": "abcdef123456", "mode": "quick", "started": "now", "elapsed": "1 min", "n": 1, "timing_fail": False}
            lanes = [{"lane": "A", "title": "t", "dir": "A", "steps": [{"id": "A01", "name": "n", "status": "pass", "ms": 5, "shots": []}], "probes": {}}]
            f = [{"lane": "A", "kind": "x", "severity": "ux", "title": "T", "now": "NOW<b>", "proposal": "PROP", "step": "A01", "shots": []}]
            p = report.render(run, lanes, f, {"found": 1, "clicked": 1, "percent": 100}, Path(d))
            h = p.read_text()
            self.assertLess(h.index("Findings"), h.index("Lane A"))
            self.assertIn("NOW&lt;b&gt;", h)


if __name__ == "__main__":
    unittest.main()
