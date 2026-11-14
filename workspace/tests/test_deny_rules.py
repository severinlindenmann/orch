"""Deny rules for orch's own folders (contracts/secrets.md, "Deny rules"; slice 1.4)."""

import json
import os
import shutil
import subprocess
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
    assert not any(f.startswith("..") for f in r["file"])  # not a valid file pattern
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
    assert not any(p.startswith("Write(") for p in pats)  # Edit covers every edit/write tool
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
        if "refuses" in c:
            from orch.errors import Refused

            with pytest.raises(Refused, match="move the workspace out of it"):
                denyrules.rules(Path(c["workspace"]), homes=c["homes"], account_home=c.get("account_home"))
            continue
        rl = denyrules.rules(Path(c["workspace"]), homes=c["homes"], account_home=c.get("account_home"))
        pats = set(_set(rl))
        for want in c.get("has", []):
            assert want in pats, (c["name"], want)
        for no in c.get("not", []):
            assert no not in pats, (c["name"], no)


# ---- review round 1 (API Opus on 1e8ed0ad)


def test_no_workspace_means_no_start_not_no_rules():
    from orch.errors import Refused

    with pytest.raises(Refused):
        denyrules.deny_args({"format": "patterns/1"}, [], None)
    assert denyrules.deny_args({"format": "none"}, ["x"], None) == ["x"]


def test_every_render_call_site_passes_a_workspace():
    import ast

    src = Path(adapters.__file__).parent
    seen = 0
    for f in src.glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text("utf-8"))):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "render"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "adapters"
            ):
                seen += 1
                assert len(n.args) >= 5 or any(k.arg == "root" for k in n.keywords), f"{f.name}:{n.lineno}"
    assert seen >= 3


def test_default_home_and_orch_home_are_always_rows(proj_ws, monkeypatch, tmp_path):
    from orch import denyrules as d

    monkeypatch.setattr("orch.humanproof.guarded_home", lambda r: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr("orch.addons.home", lambda r=None: (_ for _ in ()).throw(OSError("x")))
    other = tmp_path / "elsewhere"
    monkeypatch.setenv("ORCH_HOME", str(other))
    paths = {r["path"] for r in d.rules(proj_ws) if r["root"] == "home"}
    assert str(other) in paths
    assert any(p.endswith(".orch-tool") for p in paths)


def test_spaces_and_separators_become_wildcards_not_splits():
    rl = denyrules.rules(
        Path("/Users/My Projects/p"),
        homes=["/Users/My Projects/.orch-tool"],
        account_home="/Users/My Projects",
    )
    pats = _set(rl)
    assert "Read(//Users/My*Projects/.orch-tool/**)" in pats
    for p in pats:
        assert " " not in p and "?" not in p
    win = denyrules.rules(
        Path("C:/Users/Ann Lee/p"),
        homes=["C:\\Users\\Ann Lee\\.orch-tool"],
        account_home="C:\\Users\\Ann Lee",
    )
    for p in _set(win):
        assert " " not in p
    assert "Read(//c/Users/Ann*Lee/.orch-tool/**)" in _set(win)


@pytest.mark.parametrize(
    "extra",
    [
        ["--disallowedTools", "A,B"],
        ["--disallowed-tools", "A,B"],
        ["--disallowedTools=A,B"],
        ["--disallowedTools", "A", "--disallowed-tools", "B"],
    ],
)
def test_every_spelling_of_the_flag_is_merged_into_one(extra):
    out = denyrules.merge_flag(["--x", *extra, "--y"], ["C(d)"])
    assert out.count("--disallowedTools") == 1
    assert not any(o.startswith("--disallowed-tools") or o.startswith("--disallowedTools=") for o in out)
    val = out[out.index("--disallowedTools") + 1].split(",")
    assert {"A", "B", "C(d)"} <= set(val) and out[0] == "--x" and "--y" in out
    assert out[-2] == "--disallowedTools"  # last: the flag is variadic, nothing may follow it


@pytest.mark.parametrize("perm", ["ask", "auto", "full"])
@pytest.mark.parametrize(
    "mode,kind", [("oneshot", "fresh"), ("oneshot", "resume"), ("live", "fresh"), ("live", "resume")]
)
def test_matrix_one_flag_and_old_entries_kept(proj_ws, perm, mode, kind):
    argv = _argv("claude", kind, mode, perm, proj_ws)
    assert argv.count("--disallowedTools") == 1
    if perm != "full":
        assert "Bash(orch private:*)" in _flag(argv)


_A = {"label": "Claude", "detect": {"binary": "claude"}}


def _fake_tool(monkeypatch, tmp_path, out):
    """A `claude` on PATH whose --version prints `out`."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    exe = d / "claude"
    exe.write_text(f"#!/bin/sh\necho '{out}'\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    adapters._binary_version.cache_clear()


@pytest.mark.parametrize("out", ["", "garbage without a number", "version one point two", "7"])
def test_unreadable_version_fails_closed(monkeypatch, tmp_path, out):
    from orch.errors import Refused

    _fake_tool(monkeypatch, tmp_path, out)
    with pytest.raises(Refused, match="is missing or too old on this computer"):
        adapters.deny_version_check(_A)


def test_tool_not_found_fails_closed(monkeypatch, tmp_path):
    from orch.errors import Refused

    monkeypatch.setenv("PATH", str(tmp_path))  # no claude here
    adapters._binary_version.cache_clear()
    with pytest.raises(Refused, match="is missing or too old on this computer"):
        adapters.deny_version_check(_A)


@pytest.mark.parametrize("out", ["2.0.0 (Claude Code)", "2.1.322 (Claude Code)", "10.0.1"])
def test_new_enough_passes(monkeypatch, tmp_path, out):
    _fake_tool(monkeypatch, tmp_path, out)
    assert adapters.deny_version_check(_A) is None


@pytest.mark.parametrize("out", ["1.0.30 (Claude Code)", "1.99.99", "0.9"])
def test_old_claude_is_refused(monkeypatch, tmp_path, out):
    from orch.errors import Refused

    _fake_tool(monkeypatch, tmp_path, out)
    with pytest.raises(Refused, match="too old"):
        adapters.deny_version_check(_A)


def test_render_runs_the_version_check_for_patterns_adapters_only(proj_ws, monkeypatch):
    from orch.errors import Refused

    def boom(a, b=None):
        raise Refused("checked")

    monkeypatch.setattr(adapters, "_deny_version_ok", boom)
    with pytest.raises(Refused, match="checked"):
        _argv("claude", "fresh", "oneshot", "ask", proj_ws)
    assert _argv("codex", "fresh", "oneshot", "ask", proj_ws)  # format none: no probe


def test_the_contract_states_the_codex_limit_honestly():
    text = (CONTRACTS / "secrets.md").read_text("utf-8")
    assert "home is write-protected there" not in text


# ---- the one integration test against the real tool ----------------------------------------------
# Proves, with the real `claude`, that the generated deny flags really refuse: a Read of a canary file under
# the guarded home, and a shell command naming that path, in modes ask and full (permissions off), while the
# same prompts WITHOUT the deny flags succeed (the control: proves the tool could read it).
#
# Run it on any machine with Claude Code installed (one command, from the repo's workspace/ folder):
#
#   cd workspace && env -u CI CLAUDE_CODE_OAUTH_TOKEN="$(claude-setup-token-value)" \
#       uv run pytest tests/test_deny_rules.py -k real_claude -rs -q
#
# Needs: `claude` on PATH; CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`; claude gets an isolated HOME
# under ~/.orch-test, never your own login); the CI variable unset (CI skips it, loudly). Expected: 2 passed.
# Any missing piece = a SKIP whose message names it (`-rs` prints them). With the token set, a failing
# control is a FAIL, not a skip: the machine claims to be set up, so "cannot prove" must not look green.

CANARY = "CANARY-8f3a91"


def _skip_reason() -> str | None:
    if os.environ.get("CI"):
        return "SKIP real-claude deny test: the CI variable is set (it runs by hand, see the comment above)"
    if not shutil.which("claude"):
        return "SKIP real-claude deny test: `claude` is not on PATH"
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "SKIP real-claude deny test: CLAUDE_CODE_OAUTH_TOKEN is not set (see `claude setup-token`)"
    return None


@pytest.mark.parametrize("perm", ["ask", "full"])
def test_real_claude_refuses_a_denied_read_and_a_denied_shell_text(perm):
    import pwd
    import tempfile

    why = _skip_reason()
    if why:
        pytest.skip(why)
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    base_dir = real_home / ".orch-test"
    base_dir.mkdir(exist_ok=True)
    iso = Path(tempfile.mkdtemp(prefix="deny-real-", dir=base_dir))  # an isolated HOME for the tool
    try:
        ws = iso / "ws"
        orch_home = iso / ".orch-tool"  # the guarded home of this isolated account
        ws.mkdir()
        orch_home.mkdir()
        (orch_home / "k.txt").write_text(CANARY + "\n")
        flag = ",".join(_set(denyrules.rules(ws, homes=[str(orch_home)], account_home=str(iso))))
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(iso),
            "CLAUDE_CODE_OAUTH_TOKEN": os.environ["CLAUDE_CODE_OAUTH_TOKEN"],
        }
        mode = ["--dangerously-skip-permissions"] if perm == "full" else ["--permission-mode", "acceptEdits"]
        if (
            perm == "ask"
        ):  # headless ask refuses reads outside cwd: grant the folder, the deny must win anyway
            mode += ["--add-dir", str(orch_home)]
        prompts = (
            f"Use the Read tool on {orch_home}/k.txt and print the file's content exactly.",
            f"Use the Bash tool to run: cat {orch_home}/k.txt  and print the output exactly.",
        )

        def run(prompt, deny):
            argv = ["claude", "-p", "--output-format", "text", *mode]
            argv += ["--disallowedTools", flag] if deny else []
            r = subprocess.run(
                [*argv, "--", prompt], cwd=ws, env=env, capture_output=True, text=True, timeout=180
            )
            return r.stdout + r.stderr

        for prompt in prompts:  # control first: without the flags the tool reads it
            got = run(prompt, deny=False)
            assert CANARY in got, (
                f"control run failed (token invalid or tool cannot read here), no proof: {got[:300]}"
            )
        for prompt in prompts:
            assert CANARY not in run(prompt, deny=True), f"deny flags did not stop: {prompt}"
        print(
            f"PASS real claude ({perm}): denied Read and denied shell text refused, control read the canary"
        )
    finally:
        shutil.rmtree(iso, ignore_errors=True)  # the exact folder made above


# ---- review round 3


@pytest.mark.parametrize("perm", ["ask", "auto", "full"])
@pytest.mark.parametrize(
    "mode,kind", [("oneshot", "fresh"), ("oneshot", "resume"), ("live", "fresh"), ("live", "resume")]
)
def test_the_variadic_flag_is_last_before_the_prompt_separator(proj_ws, perm, mode, kind):
    argv = _argv("claude", kind, mode, perm, proj_ws)
    i = argv.index("--disallowedTools")
    assert argv[i + 1].count("--") == 0  # a value, never a flag
    if mode == "oneshot":
        assert argv[i + 2 :] == ["--", "p"]  # the prompt is after `--`
    else:
        assert argv[i + 2 :] == []  # nothing positional can follow it


def test_render_checks_the_binary_it_really_starts(proj_ws, monkeypatch):
    seen = []
    monkeypatch.setattr(adapters, "_deny_version_ok", lambda a, b=None: seen.append(b))
    _argv("claude", "fresh", "oneshot", "ask", proj_ws)
    assert seen == ["claude"]


def test_two_part_version_is_padded_not_refused(monkeypatch, tmp_path):
    _fake_tool(monkeypatch, tmp_path, "2.0 (Claude Code)")
    assert adapters.deny_version_check(_A) is None


def test_a_home_containing_or_equal_to_the_workspace_refuses_the_start():
    from orch.errors import Refused

    for home in ("/Users/bob/work/proj", "/Users/bob/work", "/Users/bob", "/Users/bob/work/"):
        with pytest.raises(Refused, match="move the workspace out of it"):
            denyrules.rules(Path(WS), homes=[home], account_home=ACCT)
    deep = "/Users/bob/a/b/c"
    with pytest.raises(Refused, match="move the workspace out of it"):
        denyrules.rules(Path(deep + "/d/e/ws"), homes=[deep], account_home=ACCT)
    # a home INSIDE the workspace is fine: only that subfolder is denied, never the workspace
    rl = denyrules.rules(Path(WS), homes=[WS + "/.orch-tool"], account_home=ACCT)
    assert "Read(//Users/bob/work/proj/.orch-tool/**)" in _set(rl)
    assert "Read(//Users/bob/work/proj/**)" not in _set(rl)


def test_a_non_dot_home_is_matched_in_shell_text_by_name_and_parent():
    rl = denyrules.rules(Path("/Users/bob/work/proj"), homes=["/Users/bob/orch-tool"], account_home=ACCT)
    pats = _set(rl)
    assert "Bash(*orch-tool*)" in pats
    assert "Bash(*bob/orch-tool*)" in pats
    assert "Bash(*bob\\orch-tool*)" in pats


def test_missing_claude_code_message_is_plain(monkeypatch, tmp_path):
    from orch.errors import Refused

    monkeypatch.setenv("PATH", str(tmp_path))  # no claude here
    adapters._binary_version.cache_clear()
    a = {"label": "Claude", "detect": {"binary": "claude"}}
    with pytest.raises(Refused) as e:
        adapters.deny_version_check(a)
    assert (
        str(e.value)
        == "Claude Code is missing or too old on this computer. Install or update it, then press Continue."
    )


# ---- THE isolation invariant: an agent reads and writes its own ticket copy (instruction file, skills) and
# never the orch home (keys, secrets, approvals) or other tickets' copies. Copies live NEXT TO the home
# (addons.copies_base), so the home deny stays one blanket rule and the copy is simply not under it.


def _covered(pats, tool, path):
    """A file pattern of `tool` covers `path` (patterns are //<p> and //<p>/**, or ~/ forms)."""
    p = "//" + path.lstrip("/")
    for x in pats:
        if not x.startswith(tool + "("):
            continue
        body = x[len(tool) + 1 : -1]
        if body == p or (body.endswith("/**") and (p + "/").startswith(body[:-2])):
            return True
    return False


def _copy_world(proj):
    from orch import addons

    home = addons.home(proj).resolve()
    (home / "keys").mkdir(parents=True, exist_ok=True)
    (home / "keys" / "person.key").write_text("x")
    base = addons.copies_base(home)
    own = base / "ab12cd34" / "t_own001"
    for d in (own / ".agents/skills/orch", base / "ab12cd34" / "t_other1", base / "ffff0000" / "t_9zz999"):
        d.mkdir(parents=True, exist_ok=True)
    (own / "CLAUDE.local.md").write_text("hi")
    (base / "ab12cd34" / ".owner").write_text(str(proj))
    return home, base, own


def test_copies_live_next_to_the_orch_home_never_inside_it(tmp_path):
    from orch import addons

    for h in (tmp_path / ".orch-tool", tmp_path / "x" / "toolhome", tmp_path / "y" / ".orch-dev-home"):
        h.mkdir(parents=True)
        b = addons.copies_base(h)
        assert b.parent == h.resolve().parent and h.resolve() not in (b, *b.parents)
        assert h.name not in b.name  # the home's own name is a shell deny text: never in the copies path
    assert addons.copies_base(tmp_path / ".orch-tool").name == ".orch-work"
    assert addons.copies_base(tmp_path / "x/toolhome") != addons.copies_base(tmp_path / "x/other")


def test_an_agent_in_its_copy_reads_it_but_never_the_home_or_other_copies(proj_ws):
    home, base, own = _copy_world(proj_ws)
    argv = denyrules.deny_args({"format": "patterns/1"}, [], proj_ws, own / "src")
    pats = argv[argv.index("--disallowedTools") + 1].split(",")
    for tool in ("Read", "Edit"):
        assert _covered(pats, tool, str(home))  # the WHOLE home, one blanket rule
        assert _covered(pats, tool, str(home / "keys" / "person.key"))
        assert _covered(pats, tool, str(home / "secrets" / "made-later.json"))  # created after the start
        assert _covered(pats, tool, str(base / "ab12cd34" / "t_other1" / "a.py"))  # another ticket
        assert _covered(pats, tool, str(base / "ffff0000" / "t_9zz999"))  # another workspace's copy
        assert _covered(pats, tool, str(base / "ab12cd34" / ".owner"))
        for mine in (own, own / "CLAUDE.local.md", own / ".agents/skills/orch/SKILL.md"):
            assert not _covered(pats, tool, str(mine)), (tool, mine)
    assert "Read(./.orch/secrets/**)" in pats


def test_an_agent_outside_any_copy_is_denied_every_copy(proj_ws):
    home, base, own = _copy_world(proj_ws)
    for wd in (None, proj_ws):
        argv = denyrules.deny_args({"format": "patterns/1"}, [], proj_ws, wd)
        pats = argv[argv.index("--disallowedTools") + 1].split(",")
        assert _covered(pats, "Read", str(own / "CLAUDE.local.md"))
        assert _covered(pats, "Read", str(home / "keys"))


def test_relative_paths_from_the_copy_cannot_reach_the_home_without_its_name(proj_ws):
    """The copy is not under the home: every relative path from it into the home spells the home's name,
    which the shell deny matches as text; a link planted in the copy resolves to a path the home rule
    covers."""
    home, base, own = _copy_world(proj_ws)
    argv = denyrules.deny_args({"format": "patterns/1"}, [], proj_ws, own)
    pats = argv[argv.index("--disallowedTools") + 1].split(",")
    texts = [p[len("Bash(*") : -2] for p in pats if p.startswith("Bash(*")]
    for target in (home / "keys" / "person.key", home / "consent.json"):
        rel = os.path.relpath(target, own)
        assert any(t in rel for t in texts), rel
        assert any(t in rel.replace("/", "\\") for t in texts), rel
    (own / "k").symlink_to(home / "keys")
    assert _covered(pats, "Read", os.path.realpath(own / "k" / "person.key"))


def test_windows_copy_paths_any_case_find_the_own_copy():
    bases = ["C:\\Users\\Bob\\.orch-work"]
    ws = "C:\\Users\\Bob\\proj"
    out = denyrules.copies_rules("c:/users/bob/.ORCH-WORK/ab12cd34/t_own001/src", ws, "C:\\Users\\Bob", bases)
    assert out == []  # its own copy (nothing else listed on this machine): no blanket deny over it
    out = denyrules.copies_rules("C:\\Users\\Bob\\proj", ws, "C:\\Users\\Bob", bases)
    pats = _set(out)
    assert "Read(//c/Users/Bob/.orch-work/**)" in pats and "Edit(C:/Users/Bob/.orch-work/**)" in pats
    assert "Bash(*~\\.orch-work*)" in pats and "Bash(*%USERPROFILE%\\.orch-work*)" in pats
