---
name: orch-publish
description: "{{description}}"
---
# orch publish

Share {{#files}}files and page folders{{/files}}{{#files}}{{#apps}} and {{/apps}}{{/files}}{{#apps}}small apps{{/apps}} by a link.
{{#files}}Files are encrypted on this computer before upload; the key is the part of the link after `#` and never reaches
the server. Whoever has the whole link can open it, so share it only with the people the user means.{{/files}}

{{^connected}}
## Connect

The user gets a connect line from the publish admin. Run exactly that line:

    orch publish connect <url> --workspace <ws_id> --token <token>
    orch publish profile --description "<one sentence: what this workspace is for>" --tags a,b

The profile change waits for the owner's approval. Then this skill is rewritten with what you may share.
{{/connected}}
{{#connected}}
## When to use
{{#files}}
- The user wants to send someone a file, a report, a picture or a static page.
{{/files}}
{{#apps}}
- The user wants a small working web app online: a form, a tracker, a preview, a mini tool.
{{/apps}}
- Not for messages to another workspace or the phone (that is the relay).

## Recipes
{{#files}}

**Share a file or a page folder**

    orch publish file report.pdf                 # kept 7 days (1-90 with --days N)
    orch publish file site/                      # a folder with index.html opens as a website
{{#permanent}}
    orch publish file report.pdf --permanent     # only when the user asks for "forever"
{{/permanent}}
    orch publish file report.pdf --note "Q3 numbers"   # one line shown with the file, up to 280 characters
    orch publish extend <f_id> --days 30               # keep the same link longer
    orch publish file report-v2.pdf --replace <f_id>   # new content behind the same link (only on the computer that shared it)

It prints the full link on its own line (it ends in `#k=...`). Give the user that whole line.
{{/files}}
{{#apps}}

**Put a small app online**

    orch publish new python --store sqlite tracker   # or static|node; store none|json|markdown|sqlite
    # edit tracker/, then:
    orch publish app tracker                         # private: the link carries ?token=
{{#public}}
    orch publish app tracker --public                # an open link, only when the user asks
{{/public}}
    orch publish app tracker --new-token             # a new view link; the old one stops working

Static apps take store none or markdown. The folder name is the app name.
{{/apps}}

**Look after what you shared**

    orch publish list                 # files and apps, links, end dates
    orch publish stop <app>           # pause an app
    orch publish restart <app>
    orch publish delete <f_id or app> # gone for everyone

Record every link on its ticket: `orch link add <id> --type publish --url "<link>"`.

**Describe this workspace (once, after connecting)**

    orch publish profile --description "<one sentence>" --tags a,b

The owner approves it before it takes effect; `orch publish profile` shows what waits.
{{/connected}}

## Rules
- Publish only what the user asked for. Never anything from `.orch/secrets/` or a file with keys or passwords.
- Maximum file size: 100 MB.
- `orch publish whoami` shows what this workspace may share. If something is refused, tell the user the plain reason.
