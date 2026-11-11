import os
import sys

from orch import is_record_hook

_RECORD_HOOK = is_record_hook(sys.argv[1:])
if (
    sys.argv[1:2] == ["work-check"] and "--hook" in sys.argv
) or _RECORD_HOOK:  # a tool's hook: the watchdog runs before any import
    import threading

    _dog = threading.Timer(4.0, lambda: os._exit(0))
    _dog.daemon = True
    _dog.start()
else:
    _dog = None

if _RECORD_HOOK:
    # A tool's hook: exit 2 would block the tool call. Whatever fails below (a broken install, an import that
    # no longer exists, a SystemExit), the hook ends with one stderr line, nothing on stdout, exit 0.
    try:
        from orch.cli import main  # noqa: E402

        _code = main(watchdog=_dog)
    except BaseException:  # noqa: BLE001
        _code = 2 if "--strict" in sys.argv else 0
        try:
            sys.stderr.write(("Refused: " if _code else "orch: ") + "nothing was recorded.\n")
        except BaseException:  # noqa: BLE001 - not even a closed stderr may change the exit code
            pass
    raise SystemExit(_code)

from orch.cli import main  # noqa: E402

raise SystemExit(main(watchdog=_dog))
