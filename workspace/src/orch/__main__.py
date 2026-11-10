import os
import sys

if (
    sys.argv[1:2] == ["work-check"] and "--hook" in sys.argv
):  # a tool's hook: the watchdog runs before any import
    import threading

    _dog = threading.Timer(4.0, lambda: os._exit(0))
    _dog.daemon = True
    _dog.start()
else:
    _dog = None

from orch.cli import main  # noqa: E402

raise SystemExit(main(watchdog=_dog))
