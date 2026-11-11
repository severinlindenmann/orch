"""Deny rules for orch's own folders (contracts/secrets.md, "Deny rules"; slice 1.4)."""

import json
from pathlib import Path

import pytest
from conftest import CONTRACTS

from orch import adapters, agentsdata, denyrules

NEW = "7f3c2a9e-1b4d-4c6e-9a21-5d0e8f7b3c11"
OLD = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
WS = "/Users/bob/work/proj"
HOME = "/Users/bob/.orch-tool"
ACCT = "/Users/bob"


def _set(rule_list):
    return denyrules.tool_patterns(rule_list)


def _synthetic():
    return denyrules.rules(Path(WS), homes=[HOME], account_home=ACCT)


def _flag(argv):
    assert argv.count("--disallowedTools") == 1
    return argv[argv.index("--disallowedTools") + 1].split(",")


@pytest.fixture
def proj_ws(proj, monkeypatch):
    return proj


def _argv(name, kind, mode, perm, root):
    v = {"prompt": "p", "session": OLD, "new_session": NEW, "orch_hooks_file": "h.json", "permissions": perm}
    return adapters.render(name, kind, mode, v, root)


# ---- every adapter has the same deny set, data-driven


def test_every_adapter_declares_a_deny_format_and_the_set_is_one_for_all():
    doc = agentsdata.load()["adapters"]
    assert set(doc) == {"claude", "codex", "generic"}
    for name, a in doc.items():
        assert a["deny"]["format"] in ("patterns/1", "none"), name
        if a["deny"]["format"] == "none":
            assert a["deny"]["note"], f"{name}: say what is not enforced"
    # one set: rules() takes no adapter, the format only picks how it is told
    assert {r["root"] for r in _synthetic()} == {"home", "secrets", "record", "local-id"}


@pytest.mark.parametrize("perm", ["ask", "auto", "full"])
@pytest.mark.parametrize(
    "mode,kind", [("oneshot", "fresh"), ("oneshot", "resume"), ("live", "fresh"), ("live", "resume")]
)
def test_patterns_formatted_adapters_get_the_deny_set_in_every_mode(proj_ws, perm, mode, kind):
    root = proj_ws
    argv = _argv("claude", kind, mode, perm, root)
    pats = _flag(argv)
    want = _set(denyrules.rules(root))
    assert want and set(want) <= set(pats)
    assert "Bash(orch private:*)" in pats or perm == "full"  # the existing rules are extended, not replaced
    if mode == "oneshot":
        assert argv[-2:] == ["--", "p"]


def test_none_formatted_adapters_get_no_deny_flags_and_say_so(proj_ws):
    argv = _argv("codex", "fresh", "oneshot", "ask", proj_ws)
    assert "--disallowedTools" not in argv
    for name in ("codex", "generic"):
        assert agentsdata.load()["adapters"][name]["deny"]["format"] == "none"


# ---- path variants


def test_guarded_home_forms_posix():
    r = [x for x in _synthetic() if x["root"] == "home"][0]
    assert "//Users/bob/.orch-tool" in r["file"]
    assert "~/.orch-tool" in r["file"]
    assert "../../.orch-tool" in r["file"]
    assert {"/Users/bob/.orch-tool", "~/.orch-tool", "$HOME/.orch-tool", "${HOME}/.orch-tool"} <= set(
        r["text"]
    )
    assert "../../.orch-tool" in r["text"]
    assert ".orch-tool" in r["text"]  # the folder's own name
    assert r["read"] is True


def test_windows_backslash_and_drive_forms():
    rl = denyrules.rules(
        Path("C:/Users/bob/work/proj"), homes=["C:\\Users\\bob\\.orch-tool"], account_home="C:\\Users\\bob"
    )
    r = [x for x in rl if x["root"] == "home"][0]
    assert {
        "//c/Users/bob/.orch-tool",
        "C:/Users/bob/.orch-tool",
        "c:/Users/bob/.orch-tool",
        "~/.orch-tool",
    } <= set(r["file"])
    assert {
        "C:/Users/bob/.orch-tool",
        "C:\\Users\\bob\\.orch-tool",
        "c:\\Users\\bob\\.orch-tool",
        "~\\.orch-tool",
    } <= set(r["text"])
    rec = [x for x in rl if x["root"] == "record"][0]
    assert ".orch\\record" in rec["text"] and ".orch/record" in rec["text"]


def test_realpath_and_given_path_both_covered(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    rl = denyrules.rules(link, homes=[str(tmp_path / "h")], account_home=str(tmp_path))
    paths = {r["path"] for r in rl if r["root"] == "record"}
    assert str(link / ".orch/record") in paths and str(real / ".orch/record") in paths


def test_separator_characters_in_paths_cannot_break_a_pattern():
    rl = denyrules.rules(Path("/w/a,b(c)"), homes=["/h/x,y"], account_home="/h")
    for pat in _set(rl):
        inner = pat[pat.index("(") + 1 : -1]
        assert "," not in inner and "(" not in inner and ")" not in inner


# ---- record: write denied, read allowed through orch commands; the workspace is never denied


def test_record_is_write_denied_but_not_read_denied_for_file_tools():
    pats = _set(_synthetic())
    assert "Edit(//Users/bob/work/proj/.orch/record/**)" in pats
    assert "Write(//Users/bob/work/proj/.orch/record/**)" in pats
    assert "Read(//Users/bob/work/proj/.orch/record/**)" not in pats
    assert "Read(//Users/bob/work/proj/.orch/.local-id)" not in pats
    assert "Edit(//Users/bob/work/proj/.orch/.local-id)" in pats
    # keys and orch's home: read denied as well
    assert "Read(//Users/bob/.orch-tool/**)" in pats
    assert "Read(//Users/bob/work/proj/.orch/secrets/**)" in pats


@pytest.mark.parametrize(
    "cmd",
    [
        "orch record query --json",
        "orch record tail --follow --json",
        "orch secret env databricks -- databricks jobs list",
        "orch ticket show T-1",
        "git status",
        "ls .orch/run",
    ],
)
def test_orch_commands_and_the_workspace_are_not_denied(cmd):
    texts = {p[len("Bash(*") : -2] for p in _set(_synthetic()) if p.startswith("Bash(")}
    assert not any(t in cmd for t in texts)


@pytest.mark.parametrize(
    "cmd",
    [
        "cat /Users/bob/.orch-tool/keys/x/keys.json",
        "cat ~/.orch-tool/human.key",
        "cat $HOME/.orch-tool/keys/a/profiles.toml",
        "cat ../../.orch-tool/human.key",
        "echo x > .orch/record/runs/r.jsonl",
        "sed -i s/a/b/ .orch\\record\\runs\\r.jsonl",
    ],
)
def test_shell_commands_naming_orch_folders_are_denied(cmd):
    texts = {p[len("Bash(*") : -2] for p in _set(_synthetic()) if p.startswith("Bash(")}
    assert any(t in cmd for t in texts)


def test_no_pattern_denies_the_workspace_itself():
    pats = _set(_synthetic())
    for p in pats:
        inner = p[p.index("(") + 1 : -1].strip("*")
        assert inner.rstrip("/") not in (
            WS,
            "//Users/bob/work/proj",
            ".",
            "..",
            "/",
            "~",
            "~/",
            "//Users/bob",
        )
    assert not any(p in pats for p in ("Read(//Users/bob/work/proj/**)", "Edit(//Users/bob/work/proj/**)"))


def test_existing_disallowed_list_is_extended_not_replaced():
    out = denyrules.merge_flag(["--permission-mode", "x", "--disallowedTools", "A,B"], ["C(d)"])
    assert out == ["--permission-mode", "x", "--disallowedTools", "A,B,C(d)"]
    assert denyrules.merge_flag([], ["C(d)"]) == ["--disallowedTools", "C(d)"]


def test_unknown_format_fails_closed():
    with pytest.raises(RuntimeError):
        denyrules.deny_args({"format": "weird/9"}, [], Path("/x"))


# ---- vectors (contracts/vectors/deny-v1.json)


def test_vectors():
    doc = json.loads((CONTRACTS / "vectors/deny-v1.json").read_text("utf-8"))
    for c in doc["cases"]:
        rl = denyrules.rules(Path(c["workspace"]), homes=c["homes"], account_home=c.get("account_home"))
        pats = set(_set(rl))
        for want in c.get("has", []):
            assert want in pats, (c["name"], want)
        for no in c.get("not", []):
            assert no not in pats, (c["name"], no)
