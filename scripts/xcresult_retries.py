#!/usr/bin/env python3
"""Markdown for the GitHub job summary: every UI/unit test that needed a retry (failed once, then passed) or still failed.

    python3 scripts/xcresult_retries.py <result.xcresult>

Reads `xcresulttool get test-results tests`. Never fails the job (flakes stay visible, not fatal)."""
import json
import subprocess
import sys


def nodes(n, path=()):
    yield n, path
    for c in n.get("children", []) or []:
        yield from nodes(c, path + (n.get("name", ""),))


def main(bundle):
    try:
        out = subprocess.run(["xcrun", "xcresulttool", "get", "test-results", "tests", "--path", bundle],
                             capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
    except Exception as e:  # noqa: BLE001
        print(f"### Retried tests\n\nCould not read the result bundle: {e}")
        return
    retried, failed = [], []
    for root in data.get("testNodes", []):
        for n, path in nodes(root):
            if n.get("nodeType") != "Test Case":
                continue
            runs = [c for c in n.get("children", []) or [] if c.get("nodeType") in ("Repetition", "Test Run")]
            results = [r.get("result") for r in runs] or [n.get("result")]
            name = "/".join(path[-2:] + (n.get("name", ""),))
            if n.get("result") == "Failed":
                failed.append(name)
            elif len(results) > 1 and "Failed" in results:
                retried.append(f"{name} ({', '.join(str(r) for r in results)})")
    print("### Retried tests (flaky: passed on a later try)\n")
    print("\n".join(f"- {t}" for t in retried) if retried else "None.")
    if failed:
        print("\n### Still failing after retries\n")
        print("\n".join(f"- {t}" for t in failed))


if __name__ == "__main__":
    main(sys.argv[1])
