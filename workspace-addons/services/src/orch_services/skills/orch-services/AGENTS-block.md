## orch-services
Background jobs this workspace needs (a web preview, a watcher, a local server) run as services: `orch services add "<name>" --id <slug> --ticket <id> -- <command...>`.
See them with `orch services list`; start, stop, restart, `auto <id> on|off`, `log <id>`. Read `.agents/skills/orch-services/SKILL.md`.
Share a folder by link: `orch services share <folder> --ticket <id>` prints the link to give; never start a web server by hand for it.
Jobs orch did not make: `orch services found`; Manage with orch: `orch services adopt <found-id> --ticket <id>`. orch shows found services; it changes one only after the person chooses Manage with orch.
