# Prototype checklist

Done = ticked here, tests green, and the e2e scenario (docs/e2e-scenarios.md) passed.

## W0 base
- [x] repo `orch` (develop = default branch; main is the owner's)
- [x] contracts + validate.py
- [x] CI: ci.yml path filters + gate, one workflow per folder
- [x] brand tokens + logo in brand/

## workspace
- [ ] install.sh / install.ps1, `orch update`
- [ ] `orch init`: skill, AGENTS.md, .claude/skills link (symlink / junction), .gitignore
- [ ] tickets new/list/show/status/edit/wait, one JSON per ticket, unknown fields kept; `waiting_on {kind: time|ticket|question|external}`, `revision` per write, `--if-revision`
- [ ] checklist + evidence, done needs evidence
- [ ] history log, links, ext
- [ ] ask / answer
- [ ] `orch addon add|list|remove|uninstall`: core knows no add-on by name; built-in or local folder; consent (`--yes`) bound to this machine + workspace (`.orch/.local-id`, hash for local folders); `.orch/addons.json` alone activates nothing; skill `orch-<name>` + `<!-- orch:addon:<name> -->` block; remove keeps ticket `ext` (hidden), `--purge` deletes add-on data
- [ ] publish client: connect, whoami, file share (encrypt), app deploy/list/restart/stop/delete
- [ ] relay client: connect, inbox (dedup), send, allow, refresh (+ workspaces.json, shared skills/MCP/creds), webhook
- [ ] works with no git / local git / remote git
- [ ] Windows CI smoke

## workspace-addons
- [ ] dashboard: list, detail, Inbox (relay set up), one tab per active add-on from `view --json` (stale / error states, "as of"), ticket rows from `ticket_view`, empty state, snapshot to publish without add-on content
- [ ] scheduler: `orch wait --until` wakes, `orch scheduler repeat` (cron in `ext.scheduler`), runs claude/codex/any CLI, inbox start, start/stop, tab via `view --json`
- [ ] no add-on on → no trace of scheduler/dashboard in `--help`, skills, AGENTS.md (e2e A12)

## publish
- [ ] files E2E (/f/ page decrypts), temp/permanent, sweep, 100 MB
- [ ] apps static/python/node, stores, app.toml, token/public, temp/permanent
- [ ] admin portal (private network :8411): workspaces (description, tags, rights), files, apps
- [ ] workspace API incl. whoami, onboarding.sh/.ps1
- [ ] deployed on the VPS

## relay
- [ ] admin portal (:8412): workspaces (description, tags), pair rules, messages, shared config, webhooks, phones
- [ ] inbox, dedup, offline queue, files, delegate/start + allow
- [ ] webhooks, refresh snapshot + workspaces directory
- [ ] at-rest encryption + admin read
- [ ] phone API + APNs push
- [ ] deployed on the VPS

## mobile
- [ ] onboarding link/QR, workspaces, questions + answer, push, send with voice, settings

## e2e
- [ ] all scenarios in docs/e2e-scenarios.md green (`e2e/run.sh all --mode local`, `e2e/run.sh agents`), walkthrough with screenshots (`e2e/walkthrough/run.sh`)
