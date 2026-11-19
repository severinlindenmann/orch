"""The workspace folder was moved or copied: its saved keys still belong to the old folder (ORCH-853). Then
every secret check fails closed and commands refuse in ways that look unrelated."""

from orch.diag_checks import data, verdict

NAME = "key_binding_moved"


def check(snap):
    state = data(snap, "env").get("key_binding")
    if state in (None, "unknown"):
        return verdict(NAME, "cannot_check", "the binding of the saved keys could not be read")
    if state == "moved":
        return verdict(
            NAME,
            "problem",
            "this folder was moved: its saved keys still belong to the old folder",
            ["run orch workspace move-here yourself in a terminal in this folder"],
        )
    if state == "copy":
        return verdict(
            NAME,
            "problem",
            "this folder is a copy: its saved keys belong to the original folder",
            ["work in the original folder; the copy has no saved keys of its own"],
        )
    if state == "none":
        return verdict(NAME, "ok", "no saved keys yet")
    return verdict(NAME, "ok", "the saved keys belong to this folder")
