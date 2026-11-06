"""Is a person at this terminal? The one place orch asks (never call .isatty() elsewhere).

On Windows `isatty()` is also true for the NUL device, which is what a scheduled task, a CI runner or an
agent tool often gives as stdin: orch would then wait for an answer nobody can type. There a stream counts
only when it is a real console (GetConsoleMode works on its handle)."""

from __future__ import annotations

import sys


def is_terminal(stream) -> bool:
    if stream is None:
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, OSError, ValueError):
        return False
    if sys.platform != "win32":
        return True
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return True  # a stand-in stream (tests) that says it is a terminal
    return _windows_console(fd)


def _windows_console(fd: int) -> bool:
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(fd)
    except OSError:
        return False
    mode = ctypes.c_uint32()
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
