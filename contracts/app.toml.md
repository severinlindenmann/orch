# app.toml (publish app manifest)

Every app folder has one `app.toml` at its root. `orch publish app <folder> [--days N|--permanent]` packs the folder and sends it.
Apps are temporary (default 7 days, max 90) or permanent, like files; lifetime is set at deploy, not in app.toml.

```toml
name   = "weekly-report"          # ^[a-z0-9-]{2,40}$, becomes /a/weekly-report
about  = "Weekly ticket report"   # one line, shown in the admin portal
stack  = "python"                 # static | python | node
start  = "python main.py"         # python/node only: command that starts the server
health = "/health"                # python/node only: GET must answer 200 within 20 s
test   = "python -m unittest discover -s tests"   # optional: must exit 0 before the switch
store  = "sqlite"                 # none | json | markdown | sqlite
public = false                    # false = needs ?token=<view token> (default), true = open link
```

| Field | Required | Default |
|---|---|---|
| name, stack | yes | – |
| about | no | "" |
| start, health | python/node: yes; static: not allowed | – |
| test | no | none |
| store | no | `none` |
| public | no | `false`; `true` needs the workspace right `public` |

## Stacks

| Stack | What the host does |
|---|---|
| static | Serves the files. `.md` files are shown as HTML in the orch style. `index.html` or `index.md` is the start page |
| python | Python 3.12. `requirements.txt` (if there) is installed into the app's own venv with `uv`. Stdlib or FastAPI |
| node | Node 22. `package.json` (if there): `npm ci --omit=dev` |

## Environment the host gives the app

| Var | Example | Meaning |
|---|---|---|
| `PORT` | `9104` | Listen on `127.0.0.1:$PORT` |
| `BASE_PATH` | `/a/weekly-report` | The app is served under this path; links must start with it |
| `DATA_DIR` | `/var/lib/orch-publish/apps/weekly-report/data` | The only writable folder; kept across deploys. Empty and read-only when `store = "none"` |
| `STORE` | `sqlite` | The store from app.toml. The app picks file names itself (`data.json`, `*.md`, `app.db`) |

## Sandbox (same as the orch core host)

One systemd unit per app (`orch-app@<name>.service`): own dynamic user, `ProtectSystem=strict`, `ProtectHome`,
`PrivateTmp`, `NoNewPrivileges`, `MemoryMax=128M`, `CPUQuota=25%`, `TasksMax=64`. Static apps run no process.
Templates to start from: `orch publish new <name> --stack static|python|node --store …` (copied from the orch core templates).
