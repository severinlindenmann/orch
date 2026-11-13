import json
import subprocess
import sys
from pathlib import Path

BRAND = Path(__file__).resolve().parents[1]


def test_generated_css_is_in_sync():
    r = subprocess.run([sys.executable, str(BRAND / "gen_tokens.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_check_fails_when_out_of_sync(tmp_path, monkeypatch):
    sys.path.insert(0, str(BRAND))
    import gen_tokens

    t = json.loads((BRAND / "tokens.json").read_text())
    t["color"]["brand"] = "#000000"
    assert gen_tokens.render(t) != (BRAND / "tokens.css").read_text()


def test_dark_only_and_values():
    t = json.loads((BRAND / "tokens.json").read_text())
    assert t["schema"] == "orch.tokens/1" and t["mode"] == "dark-only"
    css = (BRAND / "tokens.css").read_text()
    assert "--brand: #61d5b8;" in css and "--fs-5: 28px;" in css and "--h: 36px;" in css
    assert "--fs-body: 14px;" in css and "--row-height: 40px;" in css and "--s9: 64px;" in css
    assert "--addon: var(--brand);" in css and "#f07a2e" not in css
