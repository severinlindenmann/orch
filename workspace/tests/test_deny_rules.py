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


# ---- a ticket agent reads its own instruction file and skills in <orch home>/worktrees/<ws8>/<ticket>


def _wt_rules(tmp_path, workdir=True):
    home = tmp_path / ".orch-tool"
    for d in ("worktrees/ab12cd34/t_1", "worktrees/ab12cd34/t_2", "worktrees/ffff0000/t_9", "keys"):
        (home / d).mkdir(parents=True, exist_ok=True)
    (home / "worktrees" / "ab12cd34" / ".owner").write_text("x")
    (home / "newthing.json").write_text("{}")
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    wd = str(home / "worktrees/ab12cd34/t_1") if workdir else None
    rl = denyrules.rules(ws, homes=[str(home)], account_home=str(tmp_path))
    return home, ws, denyrules.without_worktrees(rl, str(ws), str(tmp_path), wd), wd


def test_only_the_running_tickets_folder_stays_open(tmp_path):
    home, ws, rl, wd = _wt_rules(tmp_path)
    pats = _set(rl)
    h = str(home).lstrip("/")
    for tool in ("Read", "Edit"):
        for denied in (
            "keys/**",
            "consent.json",
            "permissions.json",
            "agent-approvals.json",
            "newthing.json",
            "*.json",
            "*.tmp*",
            ".*",
            "worktrees/ffff0000/**",  # another workspace's copies
            "worktrees/ab12cd34/t_2/**",  # another ticket
            "worktrees/ab12cd34/.owner",
            "worktrees/.known.json",
        ):
            assert f"{tool}(//{h}/{denied})" in pats, (tool, denied)
        assert not any(p.startswith(f"{tool}(") and "/t_1" in p for p in pats)  # its own copy
        assert f"{tool}(//{h}/**)" not in pats and f"{tool}(//{h}/worktrees/**)" not in pats
    assert "Read(./.orch/secrets/**)" in pats
    assert "Bash(*../keys*)" in pats and "Bash(*../../*)" in pats and "Bash(*../secrets*)" in pats


def test_without_a_worktree_the_home_stays_a_blanket_deny(tmp_path):
    home, ws, rl, _ = _wt_rules(tmp_path, workdir=False)
    h = str(home).lstrip("/")
    assert f"Read(//{h}/**)" in _set(rl)
    other = denyrules.without_worktrees(rl, str(ws), str(tmp_path), str(ws))  # the workspace itself
    assert f"Read(//{h}/**)" in _set(other)


def test_a_link_out_of_the_worktree_into_the_home_refuses_the_start(tmp_path):
    from orch.errors import Refused

    home, ws, _, wd = _wt_rules(tmp_path)
    os.symlink(home / "keys", Path(wd) / "k")
    with pytest.raises(Refused, match="points into orch's own folder"):
        denyrules.check_worktree_links(wd, [str(home)])
    os.remove(Path(wd) / "k")
    os.symlink(home / "worktrees/ab12cd34/t_2", Path(wd) / "sibling")  # a sibling copy is inside the home too
    with pytest.raises(Refused):
        denyrules.check_worktree_links(wd, [str(home)])
    os.remove(Path(wd) / "sibling")
    os.symlink(Path(wd) / "a", Path(wd) / "inside")  # a link that stays in the copy is fine
    os.symlink(tmp_path, Path(wd) / "elsewhere")  # outside the home entirely: not this check's business
    denyrules.check_worktree_links(wd, [str(home / "nothere")])


def test_deny_args_with_a_workdir_checks_links_and_opens_the_copy(proj_ws, tmp_path):
    from orch.errors import Refused

    home = Path(denyrules._candidates(proj_ws)[0])
    wd = home / "worktrees/ab12cd34/t_1"
    wd.mkdir(parents=True)
    argv = denyrules.deny_args({"format": "patterns/1"}, [], proj_ws, wd)
    pats = argv[argv.index("--disallowedTools") + 1].split(",")
    assert not any(p.startswith("Read(") and "/t_1" in p for p in pats)
    os.symlink(home, wd / "up")
    with pytest.raises(Refused):
        denyrules.deny_args({"format": "patterns/1"}, [], proj_ws, wd)


def test_every_top_level_name_orch_writes_under_its_home_is_denied():
    """Fails when code names a new file or folder directly under the orch home that HOME_CHILDREN and
    HOME_PATTERNS do not cover: add it there (a deny rule has no default for names it does not know)."""
    import fnmatch
    import re

    src = Path(denyrules.__file__).parent.parent
    rx = re.compile(
        r"\b(?:home|HOME|_home|orch_home|guarded|addons\.home\([^)]*\)|home\([^)]*\))\s*/\s*\"([\w.-]+)\""
    )
    names = set()
    for f in list(src.rglob("*.py")) + list((src.parents[1] / "workspace-addons").rglob("*.py")):
        if "tests" in f.parts or ".venv" in f.parts or "node_modules" in f.parts:
            continue
        names |= set(rx.findall(f.read_text(encoding="utf-8", errors="ignore")))
    names -= {denyrules.OPEN_CHILD, ".orch-tool", ".claude", ".local", ".cache"}
    covered = set(denyrules.HOME_CHILDREN)
    missing = sorted(
        n
        for n in names
        if n not in covered and not any(fnmatch.fnmatchcase(n, p) for p in denyrules.HOME_PATTERNS)
    )
    assert not missing, f"new names under the orch home are not in denyrules.HOME_CHILDREN: {missing}"
