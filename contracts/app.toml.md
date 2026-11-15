# app.toml (publish app manifest)

Every app folder has one `app.toml` at its root. `orch publish app <folder> [--days N|--permanent]` packs the folder and sends it.
Apps are temporary (default 7 days, max 90) or permanent, like files; lifetime is set at deploy, not in app.toml.

```toml
name   = "weekly-report"          # ^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$ (2-40, starts and ends with a letter or digit), becomes /a/weekly-report
about  = "Weekly ticket report"   # one line, shown in the admin portal
stack  = "python"                 # static | python | node | docker
start  = "python3 main.py"         # python/node: command that starts the server; docker: optional, overrides the image CMD
health = "/health"                # python/node/docker: GET must answer 200 within 20 s
test   = "python3 -m unittest discover -s tests"   # optional: must exit 0 before the switch
store  = "sqlite"                 # none | json | markdown | sqlite
public = false                    # false = needs ?token=<view token> (default), true = open link
```

| Field | Required | Default |
|---|---|---|
| name, stack | yes | – |
| about | no | "" |
| start | python/node: yes; docker: optional (image CMD otherwise); static: not allowed | – |
| health | python/node/docker: yes; static: not allowed | – |
| test | no | none |
| store | no | `none` |
| public | no | `false`; `true` needs the workspace right `public` |

## Stacks

| Stack | What the host does |
|---|---|
| static | Serves the files. `.md` files are shown as HTML in the orch style. `index.html` or `index.md` is the start page |
| python | Python 3.12. `requirements.txt` (if there) is installed into the app's own venv with `uv`. Stdlib or FastAPI |
| node | Node 22. `package.json` (if there): `npm ci --omit=dev` |
| docker | Only on a server with the container engine (Kiri). The bundle has a `Dockerfile` at its top level; the host builds it and runs the image. Any language. `test` runs inside the built image |

## Environment the host gives the app

| Var | Example | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | Listen on `$HOST:$PORT`. `0.0.0.0` when the app runs in a container (only the host can reach that port) |
| `PORT` | `9104` | The port to listen on |
| `BASE_PATH` | `/a/weekly-report` | The app is served under this path; links must start with it |
| `DATA_DIR` | `/var/lib/orch-publish/apps/weekly-report/data` (`/data` in a container) | The only writable folder; kept across deploys. Empty and read-only when `store = "none"` |
| `STORE` | `sqlite` | The store from app.toml. The app picks file names itself (`data.json`, `*.md`, `app.db`) |

## Sandbox

The server picks one of three modes with `ORCH_PUBLISH_SANDBOX`:

| Mode | How an app runs |
|---|---|
| unset | A plain child process (development and tests only) |
| `systemd` | One transient unit per app: own dynamic user, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges`, `MemoryMax=256M`. Stacks static, python, node |
| `container` | One container per app on the container engine (Kiri, Docker Engine API on `ORCH_PUBLISH_ENGINE_SOCKET`, default `/run/kiri/docker.sock`). All four stacks |

Container mode, per app: its own network (one per app, so apps cannot reach each other), port published on `127.0.0.1` only, memory 128 MB, 0.5 CPU, 64
processes, read-only root with a `/tmp` tmpfs, no capabilities, `no-new-privileges`, runs as uid 61000 with the
publish server's group. Code at `/app` (read-only while running), data at `/data` (the only writable folder). python uses
`python:3.12-slim`, node `node:22-slim`; requirements are installed in a build step with network. Static apps run
no process in any mode. Listen on `$HOST`, not on a fixed `127.0.0.1`: in a container `$HOST` is `0.0.0.0` and a
loopback-only app fails its health check.

Templates to start from: `orch publish new <name> --stack static|python|node|docker --store …`.
