"""Optional in-process run hooks. Callbacks run outside the registry lock.

run_start / run_state / run_end fire after the run lock is released. The `before_paste` gate is the one
exception: deliver() asks it while holding the run lock (the paste decision and the record update must stay
atomic), so a gate function must be quick and must not take the run lock itself."""

from threading import Lock

POINTS = ("run_start", "run_state", "run_end", "before_paste", "event_line")
_lock = Lock()
_hooks = {point: [] for point in POINTS}


def _check(point):
    if point not in POINTS:
        raise ValueError(f"Unknown hook point: {point}")


def register(point, fn):
    _check(point)
    with _lock:
        _hooks[point].append(fn)


def unregister(point, fn):
    _check(point)
    with _lock:
        if fn in _hooks[point]:
            _hooks[point].remove(fn)


def reset():
    with _lock:
        for callbacks in _hooks.values():
            callbacks.clear()


def _snapshot(point):
    _check(point)
    with _lock:
        return list(_hooks[point])


def fire(point, **info):
    for fn in _snapshot(point):
        try:
            fn(**info)
        except Exception:
            pass


def gate(point="before_paste", **info) -> bool:
    allowed = True
    for fn in _snapshot(point):
        try:
            if fn(**info) is False:
                allowed = False
        except Exception:
            allowed = False
    return allowed
