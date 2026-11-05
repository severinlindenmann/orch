---
name: orch-publish
description: Publish files and small apps to private links with the orch publish service.
---
# orch publish

Publish shares a file or a small app by a private link. Files are encrypted on this machine before upload;
the key is part of the link after `#` and never reaches the server. Share the whole link, keep it private.

    orch publish whoami
    orch publish file <path or page folder> [--days N | --permanent]   (a folder needs index.html; it opens as a website)
    orch publish new static|python|node [--store none|json|markdown|sqlite] <folder>
    orch publish app <folder> [--days N | --permanent]
    orch publish list
    orch publish restart <id> | stop <id> | delete <id>

`new` copies a working template (app.toml, health path, store) into `<folder>`; the folder name is the app
name. Edit it, then deploy with `app`. Static apps allow store none or markdown.

Default lifetime is short; use `--permanent` only when the user asks. Record the link on the ticket:
`orch link add <ticket> --type publish --url "<link>"`. Never publish secrets or `.orch/secrets/`.
Maximum file size is 100 MB.

# Describe this workspace

After connecting, describe this workspace once: `orch publish profile --description "<one sentence>" --tags a,b`
The owner has to approve the change in the admin panel before it takes effect; `orch publish profile` shows what is waiting.
(no options = show it). Description up to 280 characters; up to 8 tags of 24 characters.

# Links

`orch publish file` prints the full working link on its own line (it ends in `#k=<key>`): give the user that whole line.
A private app's view link is saved in `.orch/secrets/`; deploying again or `orch publish list` shows it. Use
`orch publish app <folder> --new-token` for a new one.
