"""A helper ended its turn and sits idle while its ticket still says Working and nothing is asked (ORCH-1760).

That is how a question left only in the chat reply looks from outside: the person waits for the helper,
the helper waits for the person, and the ticket shows neither.
"""

from orch.diag_checks import data, verdict

NAME = "idle_working_no_question"
IDLE_SECONDS = 120  # a short pause between two turns is normal


def check(snap):
    tickets = data(snap, "tickets").get("tickets")
    run_recs = data(snap, "runs").get("runs") or {}
    if tickets is None:
        return verdict(NAME, "cannot_check", "tickets were not collected")
    bad = []
    for tid, t in tickets.items():
        if t.get("status") != "active" or t.get("open_questions") is None:
            continue  # an older collector without the count cannot say
        rec = run_recs.get(tid)
        if not rec or rec.get("process") == "dead" or rec.get("live_state") != "idle":
            continue
        idle = rec.get("live_age_s")
        if idle is None or idle < IDLE_SECONDS or t["open_questions"]:
            continue
        bad.append(f"{tid} - run {rec.get('run')} idle for {int(idle)} s, ticket Working, no open question")
    if bad:
        return verdict(NAME, "problem", "a helper stopped with its ticket Working and nothing asked", bad)
    return verdict(NAME, "ok", "no idle helper holds a Working ticket without a question")
