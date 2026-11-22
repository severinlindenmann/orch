"""Drafts, mockups and designs are picked only by the owner (ORCH-582, owner 18 Nov: "do not auto accept any
more draft stuff; bug fixes and follow-up problems ok; make sure there is also no automation that does that").

A draft card is a card of kind draft (`orch ask --draft`), or a choice whose options show a file (`--choose
"A=Title:draft-a.png" ...`: drafts side by side). A ticket that carries one is the owner's to accept.

Only a person signed in on the dashboard (the page hands the one orch call a one-time person grant, see
orch.renew.grant) or a paired phone (the relay checked it) answers a draft card or accepts a ticket that
carries one. Refused, with one line why, for everything else: the Reviewer (`orch review tend`), its second
look (`orch review verdict`), its routine answers (workflow.reviewer_answers), Away mode / the Auto Reviewer
(they build on the same calls), and `orch answer` / `orch review answer` from a script or a helper's shell,
whatever --by or --via it says. Bug fixes and follow-up problems (no draft card) are not touched here.
"""

from __future__ import annotations

from pathlib import Path

from orch.errors import Refused

CARD_REFUSAL = (
    "Only a person picks a draft: answer it on the dashboard or a paired phone. "
    "No script, helper, Reviewer or Away mode answers it."
)
TICKET_REFUSAL = (
    "This ticket carries a draft: only a person accepts it, on the dashboard or a paired phone. "
    "No script, helper, Reviewer or Away mode does."
)
LEFT_WHY = "it carries a draft, mockup or design: only you pick and accept it."


def is_draft_card(q) -> bool:
    """A card of kind draft, or a choice whose options show a file (drafts side by side)."""
    card = q.get("card") if isinstance(q, dict) else None
    if not isinstance(card, dict):
        return False
    kind = card.get("kind")
    if kind == "draft":
        return True
    if kind != "choice":
        return False
    pv = card.get("preview") if isinstance(card.get("preview"), dict) else {}
    opts = pv.get("options") if isinstance(pv.get("options"), list) else []
    return any(isinstance(o, dict) and isinstance(o.get("preview"), dict) for o in opts)


def draft_questions(ticket: dict) -> list[dict]:
    return [q for q in ticket.get("questions") or [] if is_draft_card(q)]


def carries_draft(ticket: dict) -> bool:
    """The ticket has a draft card, open or answered: accepting it is the owner's (also after a pick, the
    built result is a look the owner checks)."""
    return bool(draft_questions(ticket))


def waiting_pick(ticket: dict) -> list[dict]:
    """Draft cards that still wait for the owner's pick (open, not taken back)."""
    return [q for q in draft_questions(ticket) if q.get("answer") is None and q.get("taken_back") is None]


def refuse_card(q, person: bool) -> None:
    if is_draft_card(q) and not person:
        raise Refused(CARD_REFUSAL)


def refuse_ticket(ticket: dict, person: bool) -> None:
    if carries_draft(ticket) and not person:
        raise Refused(TICKET_REFUSAL)


HUMAN_REVIEW_REFUSAL = (
    "Human review needed is on for this ticket: the Auto Reviewer and Away mode leave it for you."
)


KIND_DRAFT_REFUSAL = "This ticket is a draft or design: the Auto Reviewer and Away mode leave it for you."


def refuse_auto(ticket: dict) -> None:
    """THE check for the Auto Reviewer and Away mode (ORCH-425/428) before they answer or accept anything on a
    ticket: refused for a ticket that carries a draft or is of kind draft (ORCH-645), and for one with
    Human review needed on (on by default; owner 18 Nov on ORCH-582). The plain Reviewer (`orch review
    tend`) and its second look do not ask this: they keep accepting small bug fixes whatever the switch
    says, and only drafts stop them."""
    from orch import tickets

    refuse_ticket(ticket, person=False)
    if tickets.kind(ticket) == "draft":  # a draft or design ticket (ORCH-645): only the owner accepts it
        raise Refused(KIND_DRAFT_REFUSAL)
    if tickets.human_review(ticket):
        raise Refused(HUMAN_REVIEW_REFUSAL)


def person_granted(root: Path, by: str | None) -> bool:
    """True only when the dashboard's signed-in page session handed THIS call a one-time person grant (the
    same proof as Renew/Replace): never for an agent actor, an agent tool's environment or a helper run,
    whatever --by or --via says. Uses the grant up."""
    import os

    from orch import renew, tickets

    # used up FIRST, needed or not: a grant never stays in this process's environment for a later child
    got = renew._take_grant(root) == "once"  # noqa: SLF001 - the one grant reader, never cached per process
    if (
        (by or "").startswith("agent:")
        or tickets.agent_tool()
        or any(os.environ.get(k) for k in renew.RUN_MARKS)
    ):
        return False
    return got


def waiting_rows(root: Path) -> list[dict]:
    """Every open draft card on a ticket that is not finished: the morning list's "Waiting for your pick"."""
    from orch import tickets

    out = []
    for t in tickets.list_all(root):
        if t.get("status") in ("done", "dropped") or t.get("general") is True:
            continue
        for q in waiting_pick(t):
            card = q.get("card") or {}
            out.append(
                {
                    "ticket": t["id"],
                    "key": t.get("key") or t["id"],
                    "title": t.get("title") or "",
                    "question": q["id"],
                    "card": str(card.get("title") or q.get("text") or "")[:200],
                    "asked_at": q.get("asked_at"),
                }
            )
    out.sort(key=lambda r: str(r.get("asked_at") or ""))
    return out
