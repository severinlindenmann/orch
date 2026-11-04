---
name: orch-publish
description: Publish files and small apps to private links with the orch publish service.
---
# orch publish

Publish shares a file or a small app by a private link. Files are encrypted on this machine before upload;
the key is part of the link after `#` and never reaches the server. Share the whole link, keep it private.

    orch publish whoami
    orch publish file <path> [--days N | --permanent]
    orch publish app <folder> [--days N | --permanent]
    orch publish list
    orch publish restart <id> | stop <id> | delete <id>

Default lifetime is short; use `--permanent` only when the user asks. Record the link on the ticket:
`orch link add <ticket> --type publish --url "<link>"`. Never publish secrets or `.orch/secrets/`.
Maximum file size is 100 MB.
