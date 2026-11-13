# orch iPhone app: feature inventory (develop @812c1b7, 6 Nov 2026)

## 1. Screens today (exact visible labels)
**Onboarding**: orch logo. "Let's get connected." / "Bring your workspaces along with an invitation."
- Buttons "Scan QR code" (primary, camera sheet), "Paste link" (uses clipboard if it holds orch://, else sheet).
  Hint "You get an invitation from orch on your computer." + disclosure "Get an invitation" (3 steps). DEBUG builds only: "Try a demo".
- Paste sheet: "Paste link", field "Invitation link" placeholder "orch://pair?…", "Continue", "Close". Errors:
  "Paste the link you were sent first. It starts with orch://." / "That link does not look right. Check you copied the whole link, or create a new one in orch on your computer."
- QR sheet: camera viewfinder; problems: "orch can't use the camera. Allow it in Settings, or paste the link instead." (+ "Open Settings") / "The camera is blocked on this phone. Paste the link instead." / "This device has no camera. Paste the link instead." / "The camera didn't start. Close and try again, or paste the link instead."; "Paste link", "Close".
- Found: card "Your invitation is ready" / "You were invited to connect this phone." / disclosure "Connection details". Buttons "Connect this phone" → "Connecting this phone…", "Use a different link".
- Errors: "This invitation has expired or was already used. Create a new one in orch on your computer." (button "Use a new invitation") / "Can't reach the server. Check your connection, then tap Connect this phone again."

**Notify step**: "You're connected." / "N workspaces are ready." Card "Know when you're needed." / "Get notified when your work needs an answer." + workspace names. "Allow notifications" / "Not now".

**Tab bar**: "Chats" (unread badge total) · "Settings".

**Chats tab**: search "Search chats and messages" (sections WORKSPACES · CHATS · MESSAGES; empty "No match on this phone."). Chips "All", "Needs you", "Workspaces", "Tickets" ("N questions waiting"). Empty "Nothing needs you right now." / "Nothing here yet." Pull to refresh.
Workspace row: avatar, name, amber dot if open questions, time, last line, unread. Indented ticket rows: status dot (amber needs you / green working / grey done), KEY (PIL-12), title, unread, state line ("Waiting for your answer" / "Working on it" / "Done — …" / "Did not work — …" / "Stopped").
No workspaces: "No chats yet" / "Pair a workspace to bring your work here." / "Pair a workspace". Loading skeleton rows. Floating "New chat" (pencil).

**Workspace chat**: offline banner "You're offline. Messages wait until you're online." Mine (queued: clock "Waiting to send"), theirs, system line "Ticket created: KEY · title", ticket card ("TICKET" key + pill, title, "x of y tasks", progress, "Open chat >"), questions. Empty "Say hello to <name>" / "Your first message starts a ticket." Composer "Message <name>…", note "A new message starts a new ticket", send. Info icon.

**Ticket chat**: title KEY + title, pill ("Needs you" / "Working" / "Done" / "Stopped" / "Did not work"), agent name · workspace. Collapsible "Tasks done/total" card (collapsed = next open task; open = checklist). Agent messages from "Claude · agent" with labels RESULT / DID NOT WORK / STOPPED, attachments, questions. Empty "Nothing here yet" / "Updates and results show up in this chat." Composer "Message <agent>…", note "Goes in after this step" (running) or "Saved for the next run".

**Question bubble**: "Needs you" (allow: lock + "Permission"; after: "Answered"), text, KEY + title, option buttons, "Suggested" tag on recommended. Allow buttons "Allow once" / "Always" / "Ignore". After tap: "Sending <x> in a moment…" + "Undo" (5 s) → "Sending <x>…" → "✓ <x> · answered from this phone". 409: "Already answered: <x>".

**Attachments**: image (thumbnail, title), link (icon, title, host, opens browser), file (icon, name, size, not tappable).

**New chat**: "Where should it go?" / "Pick the workspace for this topic." → "Continue" → text box, "Start" ("Starting…"), note "This starts a new ticket. You get a message when there is a result, a question or a problem."

**Chat info**: ticket: title, KEY + pill, Agent / Workspace / Updated, "WHERE IT STANDS" summary. Workspace: avatar, name, online text, description, "N TICKETS" list. Segments "Media n" / "Links n" / "Files n".

**Settings**: "Settings." / "Your connection, in one place." CONNECTION card "Your workspace server" ("● Online" / "● Offline, no connection" / "● Checking…"), "Details" (Server, This phone, "Access is managed by whoever invited you."). YOUR WORKSPACES n: name + "Online" / "Computer not reachable, last seen …" / "Offline, no connection" Hint "Need another workspace? Ask the person who invited you." Toggle "Notify me when I'm needed". "Sign out" → "Disconnect this phone? You will need a new invitation to connect again." (plus "N messages are still waiting to be sent and will be lost." when messages or answers are queued) / "Sign out of this phone" / "Cancel". Footer "orch for iOS · version (build)".
Shared error line "⚠︎ message" + "Try again". Signed out on 401: "This phone was signed out. Open the invitation you were sent to connect again."

## 2. Flows
- Pairing: `orch://pair?relay=<url>&code=pc_<22>`; no manual code entry. Add another workspace: NOT in the app (admin assigns on the relay) → v3 adds it (an invitation link/QR per workspace).
- Push: question (opens workspace chat at the question, pulsing border); text; relay pushes result/question/failure/stopped (title "KEY · title: first line"); never ack/working/note.
- Answers: options only; free-text answers (empty options) exist in contract but not in UI.
- Voice: code exists (m4a, relay transcribe, on-device fallback), not in the UI. Errors: "Allow the microphone in Settings to dictate.", "Could not start the microphone.", "Too many recordings in a row. Wait a moment and try again.", "That recording is too long. Keep it under 2 minutes."
- Theme dark only; Dynamic Type; 44 pt.

## 3. Backend (phone routes)
pair, push, workspaces, questions, messages?after, updates?workspace&ticket, blobs/<id> (GET), answer (409 already_answered), send {to,text,ticket?}, transcribe (10 MB / 2 min), signout.
ticket_view: title, status open|active|waiting|done|dropped, agent, summary, running, checklist, history_tail, attachments {kind image|link|file, title, url, blob_id, name, size}.
Question: title, text, options[], recommended; empty options = free answer; kind plain or `<add-on>:<name>`; allow = Once/Always/No.
Receipts today: relay stored (201) and the agent's `ack` update (ticket taken) + `running`. No workspace-delivered or per-message started receipt.
No phone upload route (/v1/blobs is workspace-only).

## 4. Artifacts
Evidence types pr, commit, file, url, command, note (role result|check|support). Ticket links {type github|jira|teams|file|ticket, url, title} shown as "<type> · <host>".
Published HTML: publish pages /f/<id>#k=<key> (encrypted, decrypts in the browser, sandboxed iframe preview) and /a/<name>/ apps. Today only plain links opened in the browser.
Images (thumbnail only, no zoom/share), files (no preview).

## 5. Gaps today → v3 candidates
Mic; free-text answers; add-on question kinds; status granularity; PR/commit cards; file/image/HTML preview in app; phone uploads; delivery receipts; reactions/reply; pagination; add workspace from the phone; per-workspace mute.
