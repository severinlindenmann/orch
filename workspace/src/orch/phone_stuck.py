"""The phone hears about a stuck ticket (ORCH-426): the same rows as the top of dashboard Home (stuck.py
STUCK_KINDS: a helper waiting on a person's OK on its screen, a step whose checks keep failing, a ticket the
Reviewer left for the person because it was not sure), whether or not the ticket needs a person's review.

One plain `text` message to `phones` on the ticket's thread per stuck row, the first time it is seen (or when
the same ticket gets stuck again later). Sent only while the relay add-on is on and a phone is paired with
this workspace; otherwise nothing is sent and nothing is remembered. It carries the ticket's display key and
the row's reason in plain words, never the ticket title, a command or a file. What was sent:
.orch/secrets/stuck-alerts.json, {row id: {since, id, at}}; a row that is gone is forgotten, so the next time
that ticket gets stuck the phone hears again. `sync` runs on every relay inbox pull (relay.sync_phone_views).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from orch import net

TEXT_MAX = 500
PER_PASS = 5  # at most this many new texts per inbox pull: a backlog arrives over a few pulls, never at once
_TIME = "%Y-%m-%dT%H:%M:%SZ"


def _line(text: str, n: int) -> str:
    """One plain line: control, line-break, zero-width and bidi characters become spaces, then cut to n."""
    t = re.sub(r"[\x00-\x1f\x7f-\x9f؜​-‏  ‪-‮⁠-⁤⁦-⁩﻿]", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def text(row: dict, key: str) -> str:
    """ "ORCH-12 is stuck. The helper has waited 5 min for your OK on its screen." """
    return _line(f"{key} is stuck. {row.get('text') or ''}", TEXT_MAX)


def due(rows: list[dict], sent: dict) -> list[dict]:
    """The stuck rows not sent yet (or stuck again since: a new `since`), in list order."""
    out = []
    for r in rows:
        before = sent.get(r["id"]) if isinstance(sent.get(r["id"]), dict) else None
        if before and before.get("since") == r.get("since"):
            continue
        # The Reviewer's note takes the ticket's last-change time as `since`, which moves on every touch
        # of the ticket: the same words are the same note (ORCH-1470).
        if before and r.get("kind") == "reviewer:unsure" and before.get("text") == r.get("text"):
            continue
        out.append(r)
    return out


def _state_path(root: Path) -> Path:
    return net.secrets_dir(root) / "stuck-alerts.json"


def _candidates(root: Path) -> dict[str, dict]:
    """The tickets that can be stuck (stuck.stuck_rows), read in full; the rest are passed over on their index
    row (ORCH-1622: every ticket was read on every inbox pull): a live run record on an unfinished ticket
    (waiting for an OK on its screen), a failing step on an unfinished ticket, or a ticket in Review the
    Reviewer left for the person."""
    from orch import reviewer, runs, stuck, ticketindex

    left = reviewer._read_state(root)
    ids = []
    for r in ticketindex.rows(root):
        status = r.get("status")
        if status == "review":
            if isinstance((left.get(r["id"]) or {}).get("left"), str):
                ids.append(r["id"])
        elif status not in stuck.FINISHED and (r.get("failing") or runs.read(root, r["id"]) is not None):
            ids.append(r["id"])
    return ticketindex.load(root, ids)


def sync(root: Path, now: datetime | None = None) -> list[str]:
    """Send the stuck tickets the phone has not heard about. Nothing at all while the relay add-on is off or
    no phone is paired. Returns the sent message ids."""
    from orch import addons, history, phone_view, relay, stuck  # relay calls this: keep it lazy

    if "relay" not in addons.active(root) or not phone_view._paired(root):
        return []
    now = now or datetime.now(UTC)
    shown = history.shown_json(root, list(_candidates(root).values()))
    keys = {t["id"]: t.get("key") or t["id"] for t in shown if isinstance(t.get("id"), str)}
    rows = [r for r in stuck.stuck_rows(root, shown, now.timestamp()) if r.get("ticket") in keys]
    path = _state_path(root)
    sent = net.read_json(path, {})
    sent = sent if isinstance(sent, dict) else {}
    live = {r["id"] for r in rows}
    gone = [k for k in sent if k not in live]
    for k in gone:  # no longer stuck: the next time it is, the phone hears again
        sent.pop(k)
    if gone:
        net.write_json(path, sent, private=True)
    ids = []
    for r in due(rows, sent)[:PER_PASS]:
        body = {"text": text(r, keys[r["ticket"]])}
        try:
            relay.scan_outgoing(root, body)  # never a secret leaves (R5.2); refused before anything is kept
        except Exception as exc:  # noqa: BLE001
            relay.log_send_failure(root, f"stuck alert {r['id']} not sent", exc)
            continue
        rec = {
            "since": r.get("since"),
            "text": r.get("text"),
            "id": relay.new_id(),
            "at": now.strftime(_TIME),
        }
        sent[r["id"]] = rec
        net.write_json(path, sent, private=True)  # fixed before the send: a retry is the same message
        try:
            msg = relay._message(
                root, "phones", "text", body, ticket=r["ticket"], mid=rec["id"], created_at=rec["at"]
            )
            if not msg.get("sent", True):
                relay.log_send_failure(root, f"stuck alert {rec['id']} not sent yet", "kept for the next try")
        except Exception as exc:  # noqa: BLE001  a refusal is only logged
            relay.log_send_failure(root, f"stuck alert {rec['id']} failed", exc)
            continue
        ids.append(rec["id"])
    return ids
