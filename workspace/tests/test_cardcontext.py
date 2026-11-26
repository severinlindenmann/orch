"""orch ask --said (ORCH-2183, Focused review B): a card quotes a person only from a stable reference (a
chat message id, history:<at>, rules:<n> of .orch/ask-when.md). orch copies the words, author and day from
the record; the helper never types the quote. Fixtures: wrong author, withdrawn words, changed source,
missing pointer, a changed goal, newer words; an out-of-date quote is never answered for the person and
shows no suggested answer."""

import json
import time

from orch import cardcontext, reviewer, tickets


def _say(proj, tid, by, text, chat=True):
    tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, by, text, chat=chat), by=by)
    return tickets.load(proj, tid)["history"][-1]


def _ask(run, tid, *extra):
    return run(
        "ask",
        tid,
        "Keep Windows 10 support?",
        "--option",
        "Keep",
        "--option",
        "Drop",
        "--recommend",
        "Keep",
        *extra,
        "--by",
        "agent:helper",
    )


def _item(run, tid):
    code, out, _ = run("review", "list", "--json")
    assert code == 0
    return next(x for x in json.loads(out)["cards"] if x.get("ticket") == tid)


def _edit(proj, tid, fn):
    """A hand edit of the ticket file (R1.3: plain files, fixable by hand)."""
    p = proj / ".orch" / "tickets" / f"{tid}.json"
    if not p.exists():
        p = next((proj / ".orch" / "tickets").rglob(f"{tid}*.json"))
    doc = json.loads(p.read_text(encoding="utf-8"))
    fn(doc)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_a_chat_line_is_quoted_from_the_record(proj, run, new_ticket):
    tid = new_ticket("Windows")
    line = _say(proj, tid, "human:lea", "Keep Windows 10 until March, half the sales team still uses it.")
    code, out, err = _ask(run, tid, "--said", line["id"])
    assert code == 0, out + err
    said = tickets.load(proj, tid)["questions"][0]["said"]
    assert said["words"] == line["text"] and said["by"] == "human:lea" and said["at"] == line["at"]
    assert said["src"] == "chat" and said["ref"] == line["id"]
    q = tickets.load(proj, tid)["questions"][0]
    plain = {k: v for k, v in q.items() if k != "said"}
    assert tickets.question_digest(q) != tickets.question_digest(plain)
    item = _item(run, tid)
    assert item["said"]["who"] == "person" and item["said"]["name"] == "lea"
    assert item["said"]["words"] == line["text"] and item["said"]["stale"] is None
    assert item["recommended"] == "Keep"


def test_a_history_comment_by_its_time_and_the_own_person_reads_as_you(proj, run, new_ticket, monkeypatch):
    from orch import whoami

    monkeypatch.setattr(whoami, "current", lambda root: "anna")
    tid = new_ticket("Windows")
    time.sleep(1.1)  # history times have whole seconds: not the same second as the ticket's Created line
    line = _say(proj, tid, "human:anna", "Only drop it after the March release.", chat=False)
    assert _ask(run, tid, "--said", "history:" + line["at"])[0] == 0
    item = _item(run, tid)
    assert item["said"]["who"] == "you" and item["said"]["src"] == "history"


def test_long_words_are_cut(proj, run, new_ticket):
    tid = new_ticket("Windows")
    line = _say(proj, tid, "human:lea", "word " * 80)
    assert _ask(run, tid, "--said", line["id"])[0] == 0
    words = tickets.load(proj, tid)["questions"][0]["said"]["words"]
    assert len(words) <= cardcontext.WORDS_MAX and words.endswith("...")


def test_wrong_author_is_refused(proj, run, new_ticket):
    tid = new_ticket("Windows")
    line = _say(proj, tid, "agent:helper", "The person wants to keep Windows 10.")
    code, out, err = _ask(run, tid, "--said", line["id"])
    assert code == 2 and "not a person" in out + err
    assert tickets.load(proj, tid)["questions"] == []


def test_missing_pointer_is_refused_and_no_pointer_means_no_quote(proj, run, new_ticket):
    tid = new_ticket("Windows")
    _say(proj, tid, "human:lea", "Keep it.")
    code, out, err = _ask(run, tid, "--said", "m_" + "a" * 16)
    assert code == 2 and "is not one line of" in out + err
    code, out, err = _ask(run, tid, "--said", "the last thing Lea said")
    assert code == 2 and "--said takes" in out + err
    assert _ask(run, tid)[0] == 0  # no --said: no guessed "newest words"
    assert "said" not in tickets.load(proj, tid)["questions"][0]
    assert "said" not in _item(run, tid)


def test_withdrawn_words_hide_the_quote_and_ask_again(proj, run, new_ticket):
    tid = new_ticket("Windows")
    line = _say(proj, tid, "human:lea", "Keep Windows 10.")
    assert _ask(run, tid, "--said", line["id"])[0] == 0
    _edit(
        proj, tid, lambda d: d["history"].remove(next(h for h in d["history"] if h.get("id") == line["id"]))
    )
    item = _item(run, tid)
    assert item["said"]["stale"] == "gone" and "words" not in item["said"]
    assert item["recommended"] is None and item["one_tap"] is False


def test_changed_source_hides_the_quote(proj, run, new_ticket):
    tid = new_ticket("Windows")
    line = _say(proj, tid, "human:lea", "Keep Windows 10.")
    assert _ask(run, tid, "--said", line["id"])[0] == 0

    def change(d):
        next(h for h in d["history"] if h.get("id") == line["id"])["text"] = "Drop Windows 10."

    _edit(proj, tid, change)
    item = _item(run, tid)
    assert item["said"]["stale"] == "changed" and "words" not in item["said"]


def test_a_changed_goal_and_newer_words_keep_the_quote_but_mark_it(proj, run, new_ticket):
    tid = new_ticket("Windows")
    line = _say(proj, tid, "human:lea", "Keep Windows 10.")
    assert _ask(run, tid, "--said", line["id"])[0] == 0
    time.sleep(1.1)  # history times have whole seconds
    _say(proj, tid, "human:lea", "Actually, let us talk first.")
    item = _item(run, tid)
    assert item["said"]["stale"] == "newer" and item["said"]["words"] == "Keep Windows 10."
    _edit(proj, tid, lambda d: d.update(done_when="Windows 10 is dropped"))
    assert _item(run, tid)["said"]["stale"] == "goal"


def test_team_rule_line(proj, run, new_ticket):
    tid = new_ticket("Windows")
    (proj / ".orch" / "ask-when.md").write_text(
        "# When to ask\n\n- Never drop a platform before the next release.\n", encoding="utf-8"
    )
    code, out, err = _ask(run, tid, "--said", "rules:1")
    assert code == 2 and "no words" in out + err  # a heading is not a rule
    assert _ask(run, tid, "--said", "rules:3")[0] == 0
    item = _item(run, tid)
    assert item["said"]["who"] == "rule" and item["said"]["name"] == "Team rules"
    assert item["said"]["words"] == "Never drop a platform before the next release."
    (proj / ".orch" / "ask-when.md").write_text("# When to ask\n", encoding="utf-8")
    assert _item(run, tid)["said"]["stale"] == "gone"


def test_a_secret_in_the_quoted_words_is_refused(proj, run, new_ticket):
    tid = new_ticket("Windows")
    (proj / ".orch" / "ask-when.md").write_text("- token ghp_" + "a" * 36 + "\n", encoding="utf-8")
    assert _ask(run, tid, "--said", "rules:1")[0] == 2
    assert tickets.load(proj, tid)["questions"] == []


def test_the_reviewer_never_answers_a_question_whose_quote_is_out_of_date(proj, run, new_ticket):
    tid = new_ticket("Flaky test in the run tests")
    line = _say(proj, tid, "human:lea", "Keep Windows 10.")
    code, out, err = run(
        "ask", tid, "The run test fails once in ten. Fix it now or open an issue?", "--option", "Fix it now",
        "--option", "Open an issue", "--recommend", "Fix it now",
        "--said", line["id"], "--by", "agent:helper",
    )  # fmt: skip
    assert code == 0, out + err
    t = tickets.load(proj, tid)
    q = t["questions"][0]
    later = time.time() + 3600
    assert reviewer.routine(proj, t, q, later) == (True, reviewer.ROUTINE_WHY)
    assert reviewer.quote_stale(proj, t, q) is False
    _edit(
        proj, tid, lambda d: d["history"].remove(next(h for h in d["history"] if h.get("id") == line["id"]))
    )
    rows = reviewer.answer_routine(proj, dry_run=True, now=later)
    row = next(r for r in rows if r["ticket"] == tid)
    assert row["routine"] is False and row["why"] == reviewer.QUOTE_STALE
