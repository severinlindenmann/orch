## orch-services
Background jobs this workspace needs (a web preview, a watcher, a local server) run as services: `orch services add "<name>" --id <slug> --ticket <id> -- <command...>`.
See them with `orch services list`; start, stop, restart, `auto <id> on|off`, `log <id>`. Read `.agents/skills/orch-services/SKILL.md`.
