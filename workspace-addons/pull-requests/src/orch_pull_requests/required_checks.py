"""The names of the develop rule's required checks that a green local check stands for (ORCH-1124, localcheck.py).
They are the names of CI jobs (ci.yml's roll-up job and rules.yml's word check), so this file is on the banned-word
allowlist for the roll-up job's name; nothing else belongs here."""

ROLLUP = "gate"  # ci.yml's roll-up job
WORDS = "banned-words"  # rules.yml
REQUIRED = (ROLLUP, WORDS)
