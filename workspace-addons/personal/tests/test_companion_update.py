"""orch Companion updates itself only with our notarized Developer ID signature (ORCH-1497).

The rule (setup.swift `updateRequirement`) is checked through `--check-update` / `--check-update-as`:
- our own ad-hoc build is refused (an unsigned build never counts as ours);
- a real notarized Developer ID app on this Mac is accepted under its own team and id, and refused under our team
  or with another id (so the team and the id are both enforced, and notarization is part of it);
- a copy of that app with a changed version in Info.plist is refused (no forged newer version).
URL and version rules run in `--selftest`.
"""

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SWIFT_DIR = Path(__file__).resolve().parents[3] / "companion" / "mac"
OUR_TEAM = "77D4THRYUN"

MAC = pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc"
)


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    out = tmp_path_factory.mktemp("companion-build")
    subprocess.run([str(SWIFT_DIR / "build.sh"), str(out)], check=True, capture_output=True, timeout=600)
    return out / "orch Companion.app"


def check(app, *args):
    exe = app / "Contents" / "MacOS" / "orch-companion"
    r = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=120, check=False)
    return r.stdout.strip()


def signer(path):
    r = subprocess.run(["codesign", "-dv", str(path)], capture_output=True, text=True, check=False)
    rows = dict(ln.split("=", 1) for ln in r.stderr.splitlines() if "=" in ln)
    return rows.get("Identifier"), rows.get("TeamIdentifier")


def notarized_app():
    """A notarized Developer ID app already on this Mac, small ones first (none on CI: the test then skips)."""
    for p in (
        "/Applications/Stats.app",
        "/Applications/Google Chrome.app",
        "/Applications/Visual Studio Code.app",
    ):
        if Path(p).is_dir():
            ident, team = signer(p)
            ok = subprocess.run(
                ["spctl", "--assess", "--type", "execute", p], capture_output=True, check=False
            )
            if ident and team and team != "not set" and ok.returncode == 0:
                return Path(p), ident, team
    return None


@MAC
def test_selftest_covers_urls_and_versions(app):
    assert "selftest passed" in check(app, "--selftest")


@MAC
def test_own_unsigned_build_is_refused(app):
    assert check(app, "--check-update", str(app)) == "refused"


@MAC
def test_rule_needs_our_team_our_id_and_notarization(app, tmp_path):
    found = notarized_app()
    if not found:
        pytest.skip("no notarized Developer ID app on this Mac")
    other, ident, team = found
    assert check(app, "--check-update-as", ident, team, str(other)) == "accepted"
    assert check(app, "--check-update-as", ident, OUR_TEAM, str(other)) == "refused"
    assert check(app, "--check-update-as", "io.severin.orch.companion", team, str(other)) == "refused"
    assert check(app, "--check-update", str(other)) == "refused"
    if other.stat().st_size and sum(f.stat().st_size for f in other.rglob("*") if f.is_file()) < 100_000_000:
        copy = tmp_path / other.name
        subprocess.run(["ditto", str(other), str(copy)], check=True)
        assert check(app, "--check-update-as", ident, team, str(copy)) == "accepted"
        info = copy / "Contents" / "Info.plist"
        data = plistlib.loads(info.read_bytes())
        data["CFBundleShortVersionString"] = "99.0.0"
        info.write_bytes(plistlib.dumps(data))
        assert check(app, "--check-update-as", ident, team, str(copy)) == "refused"
