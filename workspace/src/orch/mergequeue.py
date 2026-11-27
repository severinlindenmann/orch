"""Read one active provider's local queue once per pass, only if a ticket needs it."""

import json
import os
import subprocess
import sys
from functools import cached_property
from pathlib import Path

from orch import addons
from orch.errors import Refused


class Queue:
    def __init__(self, root: Path):
        self.root = root

    @cached_property
    def provider(self) -> dict | None:
        providers = [m for m in addons.active_manifests(self.root).values() if m.get("merge_queue")]
        if len(providers) > 1:
            raise Refused("More than one merge queue is on. Turn off the extra queue before merging.")
        return next(iter(providers), None)

    @cached_property
    def snapshot(self) -> dict:
        m = self.provider
        if not m:
            return {"bases": [], "entries": None}
        try:
            result = subprocess.run(
                [sys.executable, "-P", "-m", m["run"], *m["merge_queue"]["read"]],
                cwd=self.root,
                env={
                    **os.environ,
                    "ORCH_ROOT": str(self.root),
                    "ORCH_ADDON": m["name"],
                    "ORCH_BIN": addons.orch_bin(),
                },
                capture_output=True,
                timeout=10,
                check=True,
            )
            data = json.loads(result.stdout)
            if (
                isinstance(data, dict)
                and isinstance(data.get("bases"), list)
                and all(isinstance(b, str) for b in data["bases"])
                and "entries" in data
                and (
                    data["entries"] is None
                    or isinstance(data["entries"], list)
                    and all(
                        isinstance(r, dict)
                        and isinstance(r.get("url"), str)
                        and r.get("state") in ("waiting", "running", "out", "merged")
                        for r in data["entries"]
                    )
                )
            ):
                return data
        except (ValueError, subprocess.SubprocessError, OSError) as exc:
            raise Refused(f"The merge queue could not be read. Check {m['name']} and try again.") from exc
        raise Refused(f"The merge queue returned an invalid snapshot. Check {m['name']} and try again.")

    @cached_property
    def waiting(self) -> set[str]:
        return {
            row["url"].lower()
            for row in self.snapshot["entries"] or []
            if row["state"] in ("waiting", "running")
        }

    def add_args(self, url: str, ticket: str, *, first: bool = False) -> list[str]:
        m = self.provider
        if not m:
            raise Refused("No merge queue is on. Check the workspace add-ons before merging.")
        return [m["name"], *m["merge_queue"]["add"], url, "--ticket", ticket, *(["--first"] if first else [])]
