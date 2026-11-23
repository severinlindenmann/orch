"""Mail app way in (Personal > Mail): read the inbox of the accounts the person picked, find, show one mail, and put
a reply into that account's Drafts. There is no command here that delivers a mail; the person does that in Mail.

Personal runs it with {"action": ..., "values": {...}} on stdin and reads one JSON object from stdout (see
inbox.py in Personal). Plain Python 3.9 (the Mac's own python3), no packages. Values reach AppleScript only as
arguments of `on run argv`, never inside the script text. Exit codes for the self-check: 0 works, 3 needs the
person's permission, 1 stopped (one sentence on stdout).
"""

from __future__ import annotations

import json
import subprocess
import sys

sys.dont_write_bytecode = True  # a __pycache__ in this folder would change it and stop the way in

US, RS = "\x1f", "\x1e"
TIMEOUT = 50
NOT_OPEN = "Open the Mail app; Personal reads it while it is open."
ALLOW = (
    "Allow orch to use Mail once: System Settings > Privacy & Security > Automation, then press Try again."
)

COMMON = r"""
on iso(d)
	return (year of d as integer as text) & "-" & my pad(month of d as integer) & "-" & my pad(day of d) & "T" & my pad(hours of d) & ":" & my pad(minutes of d) & ":" & my pad(seconds of d)
end iso
on pad(n)
	return text -2 thru -1 of ("0" & (n as text))
end pad
on txt(v)
	if v is missing value then return ""
	set t to v as text
	-- mail text must never carry the field marks this script uses between fields
	set AppleScript's text item delimiters to {character id 30, character id 31}
	set parts to text items of t
	set AppleScript's text item delimiters to " "
	set t to parts as text
	set AppleScript's text item delimiters to ""
	return t
end txt
on inboxOf(acc)
	tell application "Mail"
		repeat with nm in {"INBOX", "Inbox"}
			try
				return mailbox (nm as text) of acc
			end try
		end repeat
	end tell
	return missing value
end inboxOf
on picked(argv, firstAcc)
	if (count of argv) < firstAcc then return {}
	return items firstAcc thru -1 of argv
end picked
on accountById(accId, accs)
	tell application "Mail"
		repeat with a in accounts
			if (id of a as text) is accId and (name of a as text) is in accs then return a
		end repeat
	end tell
	error "That account is not one you picked." number 9001
end accountById
"""

SCRIPTS = {
    "selfcheck": r"""
on run argv
	if not (application "Mail" is running) then return "NOTRUNNING"
	tell application "Mail" to return (count of accounts) as text
end run
""",
    "accounts": r"""
on run argv
	if not (application "Mail" is running) then return "NOTRUNNING"
	set out to ""
	tell application "Mail"
		repeat with a in accounts
			if enabled of a then set out to out & (name of a as text) & (character id 30)
		end repeat
	end tell
	return out
end run
""",
    # argv: limit, days, accounts...
    "list": r"""
on run argv
	if not (application "Mail" is running) then return "NOTRUNNING"
	set lim to (item 1 of argv) as integer
	set cutoff to (current date) - ((item 2 of argv) as integer) * days
	set accs to my picked(argv, 3)
	return my rows(accs, lim, cutoff, "")
end run
""",
    # argv: limit, words, accounts...
    "find": r"""
on run argv
	if not (application "Mail" is running) then return "NOTRUNNING"
	set lim to (item 1 of argv) as integer
	set accs to my picked(argv, 3)
	return my rows(accs, lim, missing value, item 2 of argv)
end run
""",
    # argv: account id, message id, accounts...
    "show": r"""
on run argv
	if not (application "Mail" is running) then return "NOTRUNNING"
	set US to character id 31
	set RS to character id 30
	set acc to my accountById(item 1 of argv, my picked(argv, 3))
	tell application "Mail"
		set m to first message of (my inboxOf(acc)) whose id is ((item 2 of argv) as integer)
		set toList to ""
		repeat with r in (to recipients of m)
			set toList to toList & my txt(address of r) & US
		end repeat
		set ccList to ""
		repeat with r in (cc recipients of m)
			set ccList to ccList & my txt(address of r) & US
		end repeat
		return my txt(sender of m) & RS & toList & RS & ccList & RS & my txt(subject of m) & RS & my iso(date received of m) & RS & my txt(content of m)
	end tell
end run
""",
    # argv: account id, message id, reply text, accounts...  A reply in Drafts, threaded to the mail; never delivered.
    "draft": r"""
on run argv
	if not (application "Mail" is running) then return "NOTRUNNING"
	set acc to my accountById(item 1 of argv, my picked(argv, 4))
	tell application "Mail"
		set m to first message of (my inboxOf(acc)) whose id is ((item 2 of argv) as integer)
		set r to reply m without opening window
		set content of r to (item 3 of argv)
		try
			save r
		on error
			close r saving yes
		end try
	end tell
	return "SAVED"
end run
""",
}

ROWS = r"""
on rows(accs, lim, cutoff, needle)
	set US to character id 31
	set RS to character id 30
	set out to ""
	set more to false
	tell application "Mail"
		repeat with acc in accounts
			set n to 0
			if (name of acc as text) is in accs then
				set mine to email addresses of acc
				set box to my inboxOf(acc)
				if box is not missing value then
					if needle is "" then
						set hits to (messages of box whose date received > cutoff or flagged status is true)
					else
						set hits to (messages of box whose subject contains needle or sender contains needle)
					end if
					repeat with m in hits
						if n is greater than or equal to lim then
							set more to true
							exit repeat
						end if
						set n to n + 1
						set toMe to false
						repeat with r in (to recipients of m)
							if (address of r) is in mine then set toMe to true
						end repeat
						set preview to ""
						try
							set preview to my txt(content of m)
							if (length of preview) > 300 then set preview to text 1 thru 300 of preview
						end try
						set out to out & (id of acc as text) & ":" & (id of m as text) & US & my txt(sender of m) & US & my txt(subject of m) & US & my iso(date received of m) & US & (read status of m as text) & US & (flagged status of m as text) & US & (toMe as text) & US & preview & RS
					end repeat
				end if
			end if
		end repeat
	end tell
	if more then set out to out & "MORE"
	return out
end rows
"""


class Stop(Exception):
    pass


def osa(action: str, args: list) -> str:
    script = SCRIPTS[action] + COMMON + (ROWS if action in ("list", "find") else "")
    try:
        p = subprocess.run(
            ["osascript", "-", *[str(a) for a in args]],
            input=script,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise Stop("Mail took too long to answer.") from None
    except OSError:
        raise Stop("osascript is missing on this computer.") from None
    if p.returncode != 0:
        err = p.stderr or ""
        if "-1743" in err or "-10004" in err:
            raise Stop(ALLOW)
        if "9001" in err:
            raise Stop("That account is not one you picked.")
        if "-1719" in err or "-1728" in err:
            raise Stop("That mail is not in the inbox any more.")
        raise Stop("Mail did not answer (" + " ".join(err.split())[:160] + ").")
    out = p.stdout.rstrip("\n")
    if out == "NOTRUNNING":
        raise Stop(NOT_OPEN)
    return out


def _who(sender: str) -> str:
    """'Petra Zingg <petra@example.ch>' -> 'Petra Zingg'; a bare address stays."""
    name = sender.split("<", 1)[0].strip().strip('"')
    return name or sender.strip("<> ")


def _rows(out: str) -> dict:
    more = out.endswith("MORE")
    if more:
        out = out[: -len("MORE")]
    items = []
    for rec in out.split(RS):
        f = rec.split(US)
        if len(f) < 8 or ":" not in f[0]:
            continue
        items.append(
            {
                "ref": f[0],
                "from": _who(f[1]),
                "subject": f[2],
                "when": f[3],
                "unread": f[4] != "true",
                "flagged": f[5] == "true",
                "to_me": f[6] == "true",
                "preview": " ".join(US.join(f[7:]).split())[:200],
            }
        )
    return {"items": items, "more": more}


def _ref(v) -> list:
    acc, _, mid = str(v or "").rpartition(":")
    if not acc or not mid.isdigit():
        raise Stop("That is not a mail of the Mail app.")
    return [acc, mid]


def run(action: str, values: dict) -> dict:
    accs = [str(a) for a in values.get("accounts") or [] if str(a).strip()]
    if action == "accounts":
        return {"accounts": [a for a in osa("accounts", []).split(RS) if a.strip()]}
    if not accs:
        raise Stop("Choose which Mail accounts count first.")
    limit = max(1, min(int(values.get("limit") or 50), 100))
    if action == "list":
        days = max(1, min(int(values.get("days") or 3), 30))
        return _rows(osa("list", [limit, days, *accs]))
    if action == "find":
        words = " ".join(str(values.get("words") or "").split())[:200]
        if not words:
            raise Stop("Say what to look for.")
        return _rows(osa("find", [limit, words, *accs]))
    if action == "show":
        f = osa("show", [*_ref(values.get("ref")), *accs]).split(RS, 5)
        f += [""] * (6 - len(f))
        return {
            "from": f[0],
            "to": [x for x in f[1].split(US) if x],
            "cc": [x for x in f[2].split(US) if x],
            "subject": f[3],
            "when": f[4],
            "text": f[5],
        }
    if action == "draft":
        text = str(values.get("text") or "").strip()
        if not text:
            raise Stop("The reply is empty.")
        ok = osa("draft", [*_ref(values.get("ref")), text, *accs]) == "SAVED"
        return {"saved": ok, "draft": str(values.get("request") or "")}
    raise Stop("Unknown action.")


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        req = {}
    action = str(req.get("action") or "")
    values = req.get("values") if isinstance(req.get("values"), dict) else {}
    if action == "selfcheck":
        try:
            osa("selfcheck", [])
        except Stop as e:
            if str(e) == NOT_OPEN:
                print("Mail is not open; it is checked when it is.")
                return 0
            print(str(e))
            return 3 if str(e) == ALLOW else 1
        return 0
    try:
        print(json.dumps(run(action, values), ensure_ascii=False))
    except Stop as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
    except (ValueError, TypeError):
        print(json.dumps({"error": "The values could not be read."}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
