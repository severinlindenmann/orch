"""Which scenarios an e2e run takes (main.py), and the parts of the full run.

The full run in parts (ORCH-2399): one job with every scenario no longer fits the 60-minute job limit. On release 52
(run 46079037055) A24 alone took 1325 s and the job was cut after V2-F2 with no scenario red; QUEUE-1 takes about 550 s.
e2e.yml therefore runs the full set as two jobs, `rest` and `long`, each well under the limit (release 53: about 21
minutes of scenarios without these two). `all` stays the whole set in one go for a local run.
"""

from __future__ import annotations

LONG = ("A24", "QUEUE-1")  # minutes each: they run together as their own part
PARTS = ("rest", "long")  # together: exactly `all`
ALONE = "V3-SIM"  # a long-lived harness, only by name
ORDER = {"W": 0, "A": 1, "P": 2, "R": 3, "M": 4, "F": 5}  # run order: W A P R M F (A0 before A4/A5)


def select(what: str, registry, smoke=(), smoke_offline=()) -> list[str]:
    """The scenario ids for `what`, in run order: smoke, smoke-offline, all, rest (all without LONG), long, or a
    comma list of ids, group letters (W A P R M F) and V2 / V3. An unknown id stays in the list: main.py says so."""
    known = [k for k in registry if k != ALONE]
    if what == "smoke":
        ids = list(smoke)
    elif what == "smoke-offline":
        ids = list(smoke_offline)
    elif what == "all":
        ids = known
    elif what == "rest":
        ids = [k for k in known if k not in LONG]
    elif what == "long":
        ids = [k for k in known if k in LONG]
    else:
        ids = []
        for w in what.split(","):
            if w in ("V2", "V3"):  # every v2 / v3 scenario (V2-*, V3-*)
                ids += [k for k in known if k.startswith(w + "-")]
            else:
                ids += [k for k in registry if k[0] == w] if len(w) == 1 else [w]
    return sorted(ids, key=lambda s: (ORDER.get(s[0], 9), int("".join(c for c in s[1:] if c.isdigit()) or 0), s))
