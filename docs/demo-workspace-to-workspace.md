# Try workspace to workspace with a demo

## What you get

A demo workspace called **Demo** runs on the team's dev machine. It is a normal orch workspace with three tickets about
a team lunch. You connect it to your relay. Then your own workspace can find it, write to it, hand it a task, open a
group chat with it and share a file, as it would with a colleague's workspace.

## Before you start

- Your own workspace, with orch installed and connected to your relay ([relay.md](relay.md)).
- Admin access to the relay page.
- The dev machine reachable from your notebook over the private network (VPN).

## Connect the demo

On the relay page (admin):

1. Click **Add workspace**, name it **Demo**, and put it in the same group as your own workspace
   (or in a group with **Talk** on).
2. Copy the text it shows and give it to the team. It holds Demo's key, so send it privately.

On the dev machine, the team saves that text as a file and runs one line:

```sh
$ scripts/demo-workspace.sh setup --prompt-file demo-prompt.txt
```

Connecting needs **one person's click on the dev machine's own screen**: Demo's dashboard opens there and asks you to
press **Continue**. The team does this, or you do it over screen sharing. The script waits for the click and then
prints:

- Demo's dashboard address (`http://develop.netbird.cloud:<port>/`), to watch Demo from your notebook;
- Demo's workspace id (`ws_…`).

Afterwards the team deletes `demo-prompt.txt`.

Back on the relay page, approve Demo's description ("plans a team lunch, books tables, answers questions").

How you see it: refresh your workspace list (Relay tab on your dashboard, or `orch relay refresh`). **Demo** is now in
it.

## What to try

**a) Send Demo a message.** From your workspace: `orch relay send <Demo's id> "Can you join the lunch on Fri?"`.
What you should see: the message arrives at Demo. Demo's answer comes back to your workspace.

**b) Hand Demo a task.** `orch relay delegate <Demo's id> "Book a table for 8" --text "Friday 12:00, 8 people"`.
What you should see: Demo's dashboard shows it under **Needs you**, with **Allow once**, **Always** and **Ignore**.

The first time, someone presses **Always** on the dev machine's screen (the same click as above). From then on your
workspace may hand Demo tasks without asking again, and your workspace gets "permanent allow saved". Each task becomes a
ticket on Demo; Demo's helper works on it, and the answer comes back to you as a message.

**c) Make a group from your ticket.** Make a ticket "Team lunch 20 Nov" in your workspace, then add Demo to its group
(on the ticket page, or `orch relay group add <ticket> <Demo's id>`).
What you should see:
- Demo gets the group and the ticket card.
- What you write into the group (`orch relay group say <ticket> "Who joins?"`), Demo reads.
- Demo's replies show up on your side.

**d) Share a file into the group.** `orch relay group share <ticket> menu.pdf` (or share it on the ticket page).
What you should see: the file arrives at Demo. A file that looks like it holds a password is refused, and nothing is
sent.

**e) On your phone.** If your phone is paired with your workspace, open the app.
What you should see: the same messages and the group with Demo.

## Stop or remove the demo

On the dev machine:

```sh
$ scripts/demo-workspace.sh status    # running? connected? anything waiting for a person?
$ scripts/demo-workspace.sh stop      # stop Demo's own services only
$ scripts/demo-workspace.sh remove    # stop it and delete the demo folders (asks first)
```

After `remove`, delete the Demo workspace on the relay page.

## If something does not work

- **The relay is offline:** messages wait on the relay and arrive once it is back. `status` shows the connection.
- **Demo is not in your list:** Demo must be in your workspace's group (or a group with **Talk** on). Then refresh again.
- **A task does not start:** it waits under **Needs you** on Demo's dashboard until someone presses **Allow once** or
  **Always**.
- **Demo's description is missing:** approve it on the relay page.
