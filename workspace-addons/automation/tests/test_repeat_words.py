"""ORCH-232: the history line of a repeat start says the plan in plain words, never the raw cron rule."""

from orch_automation.loop import repeat_words


def test_repeat_words_are_plain():
    assert repeat_words("0 */2 * * *") == "on its repeat, every 2 hours"
    assert repeat_words("*/5 * * * *") == "on its repeat, every 5 minutes"
    assert "cron" not in repeat_words("0 8 * * 1") and "*" not in repeat_words("0 8 * * 1")
    assert repeat_words("1-5/3 2,4 */3 * *") == "on its repeat"  # a custom plan: no rule on screen
