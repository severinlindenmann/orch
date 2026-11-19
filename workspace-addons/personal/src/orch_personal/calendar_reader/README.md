# orch Calendar
Read-only EventKit helper for macOS 14 or later; calendar permission belongs to its app bundle.
Python builds it with `swiftc -O -framework EventKit -o OrchCalendar.app/Contents/MacOS/orch-calendar main.swift`.
Python copies `Info.plist` to `OrchCalendar.app/Contents/Info.plist` and ad-hoc signs with `codesign -s - --force OrchCalendar.app`.
Start with `open -W -n [-g] OrchCalendar.app --args --out /absolute/answer.json --mode status|request|read` (choose a mode; `-g` is optional).
For read, add `--from YYYY-MM-DD --days N` (1–35); only request mode can ask for permission.
The whole JSON answer goes to `--out` through a `.part` file and atomic rename; stdout is unused.
It reads only calendar IDs, titles, source titles/types, editability/type, and event calendar IDs, dates, all-day flags, titles, attendee display names/current-user status, availability and time zones.
It never reads notes, locations, URLs, attendee emails, organizer emails, attachments or alarms, and never changes calendars.
