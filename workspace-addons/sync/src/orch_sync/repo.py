"""All git execution lives here. No outer-repository mutations or automatic adoption."""

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from orch import humanproof, safegit

from .paths import NEVER_SYNCED


class Refused(ValueError):
    pass


class RemoteRefused(Refused):
    """The remote itself is refused (its address or, on a test install, the local repository): never
    'offline', the step reports it as it is."""


NEEDS_NETWORK = "Sync needs an https or ssh address."


CONFIG = re.compile(
    r"core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)"
    r"|remote\.origin\.(url|fetch)|branch\.orch-state\.(remote|merge)|user\.(name|email)"
)
# Sync's extras ON TOP of core safegit's base (safegit.base_args / safegit.env are imported, never copied, so
# any core hardening applies here too). safegit's base has protocol.allow=never; sync re-allows exactly https
# and ssh. The file protocol is decided per call (see _transport): `always` only for a local remote on a TEST
# install, inspected (inspect_local) and reached with the overriding pack flags; `never` otherwise (so no
# url.insteadOf rewrite reaches a folder).
OPTIONS = (
    "protocol.https.allow=always",
    "protocol.ssh.allow=always",
    "submodule.recurse=false",
    "fetch.recurseSubmodules=false",
    "transfer.fsckObjects=true",
    "core.protectNTFS=true",
    "core.protectHFS=true",
    "commit.gpgsign=false",
    "core.symlinks=false",
)
# safegit empties core.sshCommand (it never talks to a network); an EMPTY sshCommand would be run as a shell
# command, so sync's network calls name git's own default, `ssh` from the sanitized PATH. GIT_SSH_COMMAND, if
# the person set one, still wins.
NETWORK_OPTIONS = ("core.sshCommand=ssh -o BatchMode=yes",)  # never a prompt (no terminal, nobody to answer)
# An address that was only typed (`orch sync act check`): not the person's own ssh command either, in batch mode,
# with no credential helper (safegit's empty one; helpers only for the configured origin) and no prompt; no ssh
# config, and none of the person's keys or agent identities offered to a host that was only typed.
TYPED_SSH = (
    "ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityFile=/dev/null"
    " -o IdentityAgent=none -o PubkeyAuthentication=no"
)
NETWORK = ("push", "fetch", "ls-remote", "clone")
# Options a caller must never pass to a network verb: they name the program run on the remote side.
_PACK_OPTIONS = ("--receive-pack", "--upload-pack", "--exec", "-u", "--repo", "--config", "-c")
ENV_PASSED = ("GIT_SSH", "GIT_SSH_COMMAND", "GIT_SSL_CAINFO")  # the person's own ssh/TLS setup


def null_device():
    """The hooks path that names no folder: the null device."""
    return "NUL" if os.name == "nt" else "/dev/null"


# Every command-bearing key the remote-side pack program could read from the peer's repository config,
# overridden on its own command line (after core.hooksPath): alternates commands, fsmonitor, auto gc.
PACK_OVERRIDES = (
    "core.alternateRefsCommand=",
    "core.alternateRefsPrefixes=",
    "core.fsmonitor=false",
    "receive.autogc=false",
    "gc.auto=0",
    "transfer.fsckObjects=true",
)


def pack_flag(verb):
    """Fable B1: a local-path or file:// remote runs receive-pack/upload-pack INSIDE that repository, which
    would run its own hooks and read its own config; our -c overrides do not reach that process. So the
    remote-side program is named explicitly with its hooks and every command-bearing key switched off. Never
    rely on GIT_CONFIG_PARAMETERS crossing over (git clears it for a local transport). Test installs only:
    on a real install a local remote never gets this far (validate_url)."""
    over = " ".join(f"-c {o}" for o in (f"core.hooksPath={null_device()}", *PACK_OVERRIDES))
    if verb == "push":
        return f"--receive-pack=git {over} receive-pack"
    return f"--upload-pack=git {over} upload-pack"


def is_link(path):
    """Include junctions and other Windows reparse points without following them."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    junction = getattr(os.path, "isjunction", None)
    return (
        stat.S_ISLNK(info.st_mode)
        or (junction is not None and junction(path))
        or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    )


def safe(root, relative):
    """Reject links in every component before local reads/writes."""
    p = Path(root).absolute()
    for part in Path(".orch", relative).parts:
        p /= part
        if is_link(p):
            raise Refused("Sync paths must not be links")
    return p


def local_dir(root):
    p = safe(root, "run/sync")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _bounded(cmd, env, timeout, max_output):
    """Run without buffering more than max_output bytes of stdout (Fable B3: a tree bomb lists gigabytes)."""
    with (
        tempfile.TemporaryFile() as err,
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err, env=env) as proc,
    ):
        chunks, size = [], 0
        try:
            while chunk := proc.stdout.read(65536):
                size += len(chunk)
                if size > max_output:
                    raise Refused("Too many files")
                chunks.append(chunk)
            proc.wait(timeout=timeout)
        finally:
            if proc.poll() is None:
                proc.kill()
        err.seek(0)
        return subprocess.CompletedProcess(cmd, proc.returncode, b"".join(chunks), err.read())


def base_config(true):
    """Core safegit's `-c` base for every git call (hooks off, signing/gpg no-op, no fsmonitor, ...)."""
    return safegit.base_args(true)


def base_env(root, true):
    """Core safegit's environment: no inherited GIT_* variable, sanitized PATH, no prompt/editor/askpass."""
    return safegit.env(safe(root, ""), Path(root), true)


def _transport(root, args):
    """(args, local, configured) for one call. A network verb names its remote explicitly; that remote's
    address must pass validate_url; a local one gets the hook-disabling pack flag. Callers never choose the
    remote-side program themselves. `configured`: a fetch/push/ls-remote to the configured network remote
    (`origin`), the only calls that get the person's credential helper."""
    if not args or args[0] not in NETWORK:
        return args, False, False
    rest = args[1:]
    if any(
        a == o or a.startswith(o + "=") or (o == "-u" and a.startswith("-u"))
        for a in rest
        for o in _PACK_OPTIONS
    ):
        raise Refused("Git operation failed")
    target = next((a for a in rest if not a.startswith("-")), None)
    if target is None:
        raise Refused("Git operation failed")
    if target == "origin" and args[0] != "clone":
        url = os.fsdecode(git(root, "config", "--get", "remote.origin.url").stdout).strip()
    else:
        url = target
    validate_url(url)
    if not is_local(url):
        return args, False, target == "origin" and args[0] in CREDENTIAL_VERBS
    inspect_local(
        root, url
    )  # test installs only (validate_url refused it otherwise); read-only, no git in it
    return (args[0], pack_flag(args[0]), *rest), True, False


CREDENTIAL_VERBS = ("push", "fetch", "ls-remote")


def credential_helpers(root):
    """The person's own git login for sync's calls to its configured remote (a private https repository):
    credential.helper from the person's GLOBAL git config only (~/.gitconfig, ~/.config/git/config), read
    through this wrapper (no inherited GIT_* variable, so nothing points it at another file). Never from the
    repository's config: an agent can write that, and check() refuses any credential key there. In order;
    an empty value resets the list before it, as git does. core safegit empties the helper on every call;
    git() passes these back with `-c` on that one call. Prompts stay off (GIT_TERMINAL_PROMPT=0, askpass)."""
    r = git(root, "config", "-z", "--global", "--get-all", "credential.helper", allowed_codes=(0, 1))
    if r.returncode:
        return []
    values = os.fsdecode(r.stdout).split("\0")[:-1]
    if any(len(v) > 4096 or "\n" in v for v in values):
        return []  # not a helper line git itself would take: no login rather than a wrong one
    # ~/.gitconfig is writable by any process of the same user (an agent too): only git's own helpers by bare
    # name; never `!command`, a path to a program (Opus hard3 #8) or any option (`store --file=…` or
    # `cache --socket=…` would point git at a file an agent chose). Anything else: no login.
    if not all(v == "" or v in HELPERS for v in values):
        return []
    return values


HELPERS = (
    "osxkeychain",
    "manager",
    "manager-core",
    "libsecret",
    "cache",
    "store",
    "wincred",
)  # exact values only


def git(
    root, *args, input=None, timeout=60, index=None, allowed_codes=(0,), commit_date=None, max_output=None
):
    work = safe(root, "")
    gd = safe(root, ".git")
    if not work.is_dir() or (gd.exists() and not gd.is_dir()):
        raise Refused(".orch and .git must be real directories")
    if not gd.exists() and args[0] not in ("init", "--version", "ls-files"):
        raise Refused("No state repository")  # never discover the outer repo
    args, local, configured = _transport(root, args)
    true = safegit.trivial("true", work, Path(root))
    if true is None:
        raise Refused("Git operation failed")
    helpers = credential_helpers(root) if configured else []
    env = base_env(root, true)
    env.update({k: os.environ[k] for k in ENV_PASSED if k in os.environ})
    env.pop("SSH_ASKPASS", None)
    if args[0] in NETWORK and not configured:
        env.pop("GIT_SSH", None)
        env["GIT_SSH_COMMAND"] = TYPED_SSH
    if commit_date is not None:
        env.update(GIT_AUTHOR_DATE=commit_date, GIT_COMMITTER_DATE=commit_date)
    if index is not None:
        env["GIT_INDEX_FILE"] = str(Path(index).absolute())
    if local:  # the pack program in the peer's repository reads no system or global config either
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=null_device())
    # Fresh private empty directory: never trust an existing attributes file.
    with tempfile.TemporaryDirectory(dir=local_dir(root)) as empty:
        attrs = Path(empty) / "attributes"
        attrs.touch()
        opts = (
            *OPTIONS,
            f"protocol.file.allow={'always' if local else 'never'}",
            *(NETWORK_OPTIONS if args[0] in NETWORK else ()),
            f"core.hooksPath={null_device()}",
            f"core.attributesFile={attrs}",
            # after the base's empty credential.helper (a reset): the person's global helpers, in order
            *(f"credential.helper={h}" for h in helpers),
        )
        cmd = [
            "git",
            "-C",
            str(work),
            "--no-replace-objects",
            *base_config(true),
            *[v for opt in opts for v in ("-c", opt)],
            *args,
        ]
        try:
            if max_output is not None and input is None:
                result = _bounded(cmd, env, timeout, max_output)
            else:
                result = subprocess.run(
                    cmd, input=input, capture_output=True, env=env, timeout=timeout, check=False
                )
            if result.returncode not in allowed_codes:
                raise Refused("Git operation failed")
            return result
        except (OSError, subprocess.SubprocessError) as e:
            raise Refused("Git operation failed") from e


def version_ok(root=None):
    if root is None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".orch").mkdir()
            return version_ok(root)
    m = re.search(rb"git version (\d+)\.(\d+)\.(\d+)", git(root, "--version").stdout)
    return bool(m and tuple(map(int, m.groups())) >= (2, 45, 1))


def check(root):
    gd = safe(root, ".git")
    if not gd.is_dir():
        raise Refused(".git must be a real directory")
    # lstat detects dangling links too; reject indirection before invoking git.
    for name in ("commondir", "gitdir", "config.worktree", "objects/info/alternates", "info/grafts"):
        path = gd / name
        parent = gd
        for part in Path(name).parts[:-1]:
            parent /= part
            if is_link(parent):
                raise Refused("unexpected git settings")
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        raise Refused("unexpected git settings")
    replace = gd / "refs/replace"
    if (
        is_link(gd / "refs")
        or is_link(replace)
        or (replace.exists() and (not replace.is_dir() or any(replace.iterdir())))
    ):
        raise Refused("unexpected git settings")
    if not version_ok(root):
        raise Refused("Update git to 2.45.1 or newer to use sync")
    common = os.fsdecode(git(root, "rev-parse", "--git-common-dir").stdout).strip()
    if (Path(root) / ".orch" / common).resolve() != gd.resolve():
        raise Refused("unexpected git settings")
    safe(root, ".git/config")
    records = git(root, "config", "--list", "--show-origin", "--show-scope", "-z").stdout.split(b"\0")
    if records.pop() != b"" or len(records) % 3:
        raise Refused("unexpected git settings")
    for scope, origin, record in zip(records[::3], records[1::3], records[2::3]):
        if scope not in (b"local", b"worktree"):
            continue
        if scope == b"worktree" or origin != b"file:.git/config":
            raise Refused("unexpected git settings")
        key, _, value = record.partition(b"\n")
        if not CONFIG.fullmatch(key.decode("utf-8")):
            raise Refused("unexpected git settings")
        if key == b"remote.origin.url":
            validate_url(value.decode("utf-8"))
    hooks = safe(root, ".git/hooks")
    if hooks.exists() and any(p.is_symlink() or not p.name.endswith(".sample") for p in hooks.iterdir()):
        raise Refused("unexpected hook, sync stopped")
    attrs = safe(root, ".git/info/attributes")
    if attrs.exists() and attrs.read_bytes().strip():
        raise Refused("unexpected git attributes")


def state(root):
    gd = safe(root, ".git")
    if gd.exists():
        check(root)
        return "ready" if safe(root, ".git/orch-state").is_file() else "needs-adoption"
    # Read-only discovery from .orch before init; no command ever changes the outer repo.
    if any((p / ".git").exists() for p in (Path(root), *Path(root).parents)):
        # Core's one discovery (the same list Move removes): the team's own files do not count. Fails closed:
        # when git cannot tell, or the index holds a name core does not accept, it stays needs-move.
        from orch import harness

        try:
            private = harness.private_tracked(Path(root))
        except Exception:  # noqa: BLE001 - unknown state is never 'new'
            return "needs-move"
        if private is None:
            return "needs-move"
        return "needs-move" if private else "new"
    return "new"


# Any trace of the sync add-on's local state means "synced before" (never adopt). The whole run/sync folder
# counts too (an agent deleting single files must not get adoption). The first `orch sync set` (local or
# remote) calls _history_on before it writes anything there; a step only reaches it once `set` has run.
EARLIER = (
    "run/sync/state.json",
    "run/sync/pending.json",
    "run/sync/choices.json",
    "run/sync/held",
    "run/sync/settings.json",
    "run/sync",
)


def _history_on(root):
    """Sync is on here from now on: core's one rule for person fields applies (orch.history). Recorded in the
    guarded orch home (keyed by real path and workspace id) FIRST, whatever state the repository is in and
    before anything can refuse, so removing .git or run/sync never makes the workspace trust every line again.
    Only a workspace that never synced (no state repository, no earlier step's state) adopts the lines already
    in its tickets as this machine's own; core never adopts when a ticket shows sync's traces."""
    from orch import history

    fresh = not os.path.lexists(safe(root, ".git")) and not any(
        os.path.lexists(safe(root, p)) for p in EARLIER
    )
    try:
        adopted = history.enable_sync(Path(root), adopt=fresh)
    except Exception as e:  # noqa: BLE001 - the guarded home refused: sync does not start
        raise Refused(f"Sync could not be turned on here: {e}") from None
    if adopted:  # once per workspace: the signed record of this machine's own add-on values starts empty
        from .approval import start_local_ext

        start_local_ext(root)


def ensure(root):
    _history_on(root)  # before state(): a missing marker or a damaged repository still records it
    current = state(root)
    if current in ("new", "ready"):
        from orch import tickets  # adopt this machine's own sessions BEFORE any remote ticket can arrive

        tickets.adopt_own_sessions(Path(root))
    if current == "ready":
        return
    if current == "needs-move":
        raise Refused(
            'needs-move: your orch files are kept in your team repository. Answer "Move your orch files out '
            'of the team repository?" first; sync starts after that'
        )
    if current != "new":
        raise Refused(f"{current}: explicit consent flow is not available yet")
    if not version_ok(root):
        raise Refused("Update git to 2.45.1 or newer to use sync")
    # Fable B8: build the repository aside and move it into place only once it is marked and checked, so an
    # interruption never leaves a markerless .git (which would read as a user's repo needing adoption).
    scratch = safe(root, "run/tmp-init")
    _clear(scratch)
    scratch.mkdir(parents=True)
    git(root, "init", "-b", "orch-state", "--template=", str(scratch))
    built = scratch / ".git"
    (built / "info").mkdir(exist_ok=True)
    (built / "info/exclude").write_text("\n".join(NEVER_SYNCED) + "\n")
    (built / "info/attributes").write_text("")
    (built / "orch-state").write_text("1\n")
    os.rename(built, safe(root, ".git"))
    try:
        check(root)
    except Exception:
        os.rename(safe(root, ".git"), built)  # back out: the next run starts again from 'new'
        raise
    _clear(scratch)


def _clear(p):
    """Remove one exact path we own; never follow a link."""
    if is_link(p):
        if os.name == "nt" and not p.is_symlink():
            p.rmdir()
        else:
            p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def recover(root):
    scratch = safe(root, "run/tmp-sync")
    if scratch.exists():
        for p in scratch.iterdir():
            if is_link(p):
                if os.name == "nt" and not p.is_symlink():
                    p.rmdir()  # remove the junction itself, never its target
                else:
                    p.unlink()
            elif not p.is_dir():
                p.unlink()
            else:
                shutil.rmtree(p)  # exact enumerated child; never follow a link


HELPER = re.compile(r"[A-Za-z0-9][A-Za-z0-9+.-]*::")  # git's `<transport>::<address>` (ext::, fd::, ...)


def is_local(url):
    """A plain absolute local path or a file:// URL without a host: git's `file` transport."""
    parsed = urlsplit(url)
    return not HELPER.match(url) and (
        Path(url).is_absolute()
        or (parsed.scheme == "file" and parsed.path.startswith("/") and parsed.netloc == "")
    )


def local_allowed():
    """Local folder and file:// remotes: TEST installs only (the same install-kind check the guarded home
    uses; the installer's record decides, no environment variable). git runs receive-pack/upload-pack inside
    such a repository, whose own config can name commands; a real install never does that. (Local folder
    remotes such as a NAS or USB disk: possibly a later feature.)"""
    return humanproof.install_kind() == "test"


def validate_url(url):
    """Only https and ssh (also scp-like git@host:path). Everything else (a local path, file://, ext::, fd::,
    git://, http://, any other transport or helper) is refused; on a TEST install a plain absolute local path
    or a file:// URL is allowed too (inspected before every use, see inspect_local)."""
    if not url or any(c.isspace() or ord(c) < 32 for c in url) or url.startswith("-") or HELPER.match(url):
        raise RemoteRefused(NEEDS_NETWORK)
    parsed = urlsplit(url)
    if parsed.password is not None or (parsed.scheme in ("http", "https") and "@" in parsed.netloc):
        raise RemoteRefused("Use your own git login, orch does not store passwords")
    if is_local(url):
        if not local_allowed() or "%" in url:  # '%': git opens a file:// path undecoded; never guess
            raise RemoteRefused(NEEDS_NETWORK)
        return
    if not (
        re.fullmatch(r"git@[A-Za-z0-9.-]+:[^\s]+", url)
        or (parsed.scheme in ("https", "ssh") and parsed.hostname)
    ):
        raise RemoteRefused(NEEDS_NETWORK)


LOCAL_REMOTE_CONFIG = re.compile(
    r"core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)"
)
LOCAL_REMOTE_REFUSED = "This local remote is not a plain bare repository; sync stopped"


def local_path(url):
    """The folder git opens for a local remote address (validate_url passed)."""
    parsed = urlsplit(url)
    return Path(parsed.path) if parsed.scheme == "file" else Path(url)


def inspect_local(root, url):
    """Test installs: before every push/fetch to a local remote, look at it read-only WITHOUT running git inside
    it. Refused unless it is a bare repository with no alternates (objects/info/alternates, http-alternates),
    no indirection (.git, commondir, gitdir, config.worktree, grafts), no link where git reads, only *.sample
    hooks, and a config (read from our side: `git config --file`, includes off) with only allowlisted keys
    (so no include.*/includeIf.*, no command-bearing key) and core.bare=true. The pack program still overrides
    every command-bearing key (pack_flag): this is the outer layer."""
    if not local_allowed():
        raise RemoteRefused(NEEDS_NETWORK)
    bare = local_path(url)

    def refuse():
        return RemoteRefused(LOCAL_REMOTE_REFUSED)

    if bare.is_absolute() and not os.path.lexists(bare):
        raise Refused(
            "Git operation failed"
        )  # an unplugged disk is offline; git never runs (no <path>.git guess)
    if not bare.is_absolute() or is_link(bare) or not bare.is_dir():
        raise refuse()
    # git would open <path>/.git before <path> itself; any of these points git at other files
    for name in (
        ".git",
        "commondir",
        "gitdir",
        "config.worktree",
        "info/grafts",
        "objects/info/alternates",
        "objects/info/http-alternates",
    ):
        if os.path.lexists(bare / name):
            raise refuse()
    for name in ("HEAD", "config", "objects", "refs", "objects/info", "info", "hooks"):
        if is_link(bare / name):
            raise refuse()
    config = bare / "config"
    if (
        not (bare / "HEAD").is_file()
        or not config.is_file()
        or not (bare / "objects").is_dir()
        or not (bare / "refs").is_dir()
        or config.stat().st_size > 65536
    ):
        raise refuse()
    hooks = bare / "hooks"
    if os.path.lexists(hooks) and (
        not hooks.is_dir()
        or any(is_link(p) or not p.is_file() or not p.name.endswith(".sample") for p in hooks.iterdir())
    ):
        raise refuse()
    try:
        listed = git(root, "config", "--file", str(config), "--no-includes", "--list", "-z").stdout
    except Refused:
        raise refuse() from None
    records = listed.split(b"\0")
    if records.pop() != b"":
        raise refuse()
    values = {}
    for record in records:
        key, newline, value = record.partition(b"\n")
        key = key.decode("utf-8", "replace")
        if not LOCAL_REMOTE_CONFIG.fullmatch(key):
            raise refuse()
        values[key] = value.decode("utf-8", "replace").lower() if newline else "true"
    if values.get("core.bare") not in ("true", "yes", "on", "1"):
        raise refuse()


def fetch(root, timeout=60):
    """Fable A11/B3: fetch only the state branch, never every branch a peer pushes. A remote without the
    branch yet (a new empty repository) is empty, not offline."""
    ref = "refs/remotes/origin/orch-state"
    # The exit code says whether the branch is there (2 = absent), never a text the remote can print or that
    # depends on git's language.
    probe = git(
        root,
        "ls-remote",
        "--exit-code",
        "origin",
        "refs/heads/orch-state",
        timeout=timeout,
        allowed_codes=(0, 2),
    )
    if probe.returncode == 2:
        git(root, "update-ref", "-d", ref)
        return
    git(root, "fetch", "--no-tags", "origin", f"+refs/heads/orch-state:{ref}", timeout=timeout)


def push(root, head, timeout=60):
    """Push `head` as the state branch. True when the remote took it; False when it refused it as not a fast
    forward (someone pushed first: fetch and merge again). Read from git's --porcelain lines on stdout (flag
    `!` and `[rejected]`), never from stderr, which the remote side can write to and which depends on git's
    language."""
    pushed = git(
        root,
        "push",
        "--porcelain",
        "origin",
        f"{head}:refs/heads/orch-state",
        timeout=timeout,
        allowed_codes=(0, 1),
    )
    lines = pushed.stdout.splitlines()
    if any(line.startswith(b"!\t") and b"\t[rejected]" in line for line in lines):
        return False
    if pushed.returncode == 0 and not any(line.startswith(b"!") for line in lines):
        return True
    raise Refused("Git operation failed")


def set_remote(root, url):
    validate_url(url)
    check(root)
    git(root, "config", "--local", "--replace-all", "remote.origin.url", url)
    git(
        root,
        "config",
        "--local",
        "--replace-all",
        "remote.origin.fetch",
        "+refs/heads/orch-state:refs/remotes/origin/orch-state",
    )
