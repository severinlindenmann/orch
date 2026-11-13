"""Keep the old orch until the new one is in place.

`uv tool install --reinstall` removes the old tool environment before it installs the new one; when the
install then fails (no internet, an executable in the way), uv also drops the half-built new one, and the
person had no orch at all. backup_tool copies the environment and its bin entries first; restore_tool puts
them back after any failure. Standalone on purpose (no orch imports, no __future__): the Windows finisher
carries this file's code.
"""

import os as _os
import shutil as _shutil

FETCH_WORDS = (
    "failed to fetch",
    "could not resolve",
    "dns error",
    "connection refused",
    "connection reset",
    "timed out",
    "network",
    "tls",
    "certificate",
    "error sending request",
    "no route to host",
    "connect error",
    "failed to download",
)
STILL_OLD = "orch is still the old version"


def backup_tool(env, bins):
    # A copy of the tool environment and its bin entries, beside it; None when there is nothing to keep.
    env = str(env)
    if not _os.path.isdir(env):
        return None
    bak = env + ".orch-backup"
    for old in (bak, bak + "-bin"):
        if _os.path.lexists(old):
            _shutil.rmtree(old, ignore_errors=True)
    _shutil.copytree(env, bak, symlinks=True)
    _os.makedirs(bak + "-bin")
    kept = []
    for i, b in enumerate(bins or []):
        b = str(b)
        if _os.path.islink(b):
            kept.append([b, "link", _os.readlink(b)])
        elif _os.path.isfile(b):
            copy = _os.path.join(bak + "-bin", str(i))
            _shutil.copy2(b, copy)
            kept.append([b, "file", copy])
    return {"env": env, "bak": bak, "bins": kept}


def _drop(path):
    if _os.path.islink(path) or _os.path.isfile(path):
        _os.remove(path)
    elif _os.path.isdir(path):
        _shutil.rmtree(path)


def restore_tool(state):
    # Put the old environment and bin entries back. True when everything is back.
    if not state:
        return False
    ok = True
    try:
        if _os.path.lexists(state["env"]):
            _drop(state["env"])
        _os.rename(state["bak"], state["env"])
    except OSError:
        ok = False
    for path, kind, what in state["bins"]:
        try:
            if _os.path.lexists(path):
                if kind == "link" and _os.path.islink(path) and _os.readlink(path) == what:
                    continue
                _drop(path)
            _os.makedirs(_os.path.dirname(path), exist_ok=True)
            if kind == "link":
                _os.symlink(what, path)
            else:
                _shutil.copy2(what, path)
        except OSError:
            ok = False
    discard_backup(state)
    return ok


def discard_backup(state):
    if state:
        for old in (state["bak"], state["bak"] + "-bin"):
            if _os.path.lexists(old):
                _shutil.rmtree(old, ignore_errors=True)


def plain_reason(detail, restored):
    # The plain words the page and the terminal show for a failed reinstall.
    t = (detail or "").lower()
    if not restored:
        return "The update failed and orch could not be put back. Run the orch install script again."
    if any(w in t for w in FETCH_WORDS):
        return "No internet connection to GitHub - " + STILL_OLD + ". Try again later."
    if "already exists" in t:
        return "Another program named orch is in the way - " + STILL_OLD + ". Try again later."
    if "took too long" in t:
        return "The update took too long - " + STILL_OLD + ". Try again later."
    return "The reinstall failed - " + STILL_OLD + ". Try again later."
