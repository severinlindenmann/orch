import os
import sys
from pathlib import Path

from orch_automation import orchcli
from orch_automation.cli import find_workspace, main


def run(argv: list[str]) -> int:
    print("The scheduler is now called automation: orch automation " + " ".join(argv))
    root = find_workspace(Path(os.environ.get("ORCH_ROOT") or "."))
    if root is not None and orchcli.addon_on(root, "automation") is False:
        print("Turn it on first: orch addon add automation", file=sys.stderr)
        return 2
    return main(argv)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
