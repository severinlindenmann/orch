"""This machine's sync settings: .orch/run/sync/settings.json (never synced, written only by `orch sync set`).
Nothing synced (config.toml, tickets, environment) can change them."""

DEFAULTS = {"mode": "off", "interval": 15, "kind": "private"}
FILE = "run/sync/settings.json"
LOCAL = 5  # minutes: local mode commits what changed, every 5 minutes at most
INTERVALS = (5, 15, 60)  # minutes a remote sync may wait; anything else is 15
DEFAULT = 15


def minutes(settings):
    if settings.get("mode") == "local":
        return LOCAL
    n = settings.get("interval")
    return n if type(n) is int and n in INTERVALS else DEFAULT
