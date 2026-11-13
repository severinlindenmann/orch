# Add-on question kinds

A ticket question may carry `kind: "<add-on>:<name>"` and an opaque `action` object (ticket.schema.json). The core only
stores them and shows the question like any other; the add-on with that prefix acts on the answer when it runs (an
answer recorded while it is off waits; `orch answer` says "Recorded. <add-on> acts on it when it runs."). Any surface may
answer (`via` is a free word). These are the kinds the shipped add-ons use:

| kind | asked by | options | `action` | what the answer does |
|---|---|---|---|---|
| `automation:failure` | automation, when a run failed or hit its limit | `Try again` · `Leave it` | `{"run": "r_…", "exit": <int> \| null, "at": "<planned run time, UTC Z>"}` | `Try again` = one new run of the ticket now (through `orch run start`); `Leave it` = nothing, the next planned run happens as usual |
| `relay:allow` | relay, for a `delegate` / `start` message without an allow | `Allow once` · `Always` · `Ignore` | `{"message": "m_…", "peer": "ws_…", "kind": "delegate" \| "start", "key": "<start key>" \| null}` | `Allow once` / `Always` = `orch relay allow <message> --once` / `--permanent`; `Ignore` (old `No` still accepted) = the message is dropped with a note (`inbox-notes.json`) |
| `focus:permission` | focus, when the agent's tool was denied a permission (run event `denial`) | `Allow once` · `No` | `{"run": "r_…", "tool": "<tool name>", "input": "<short redacted summary>"}` | `Allow once` = the run is resumed once with that tool allowed (adapter `allow_args`); `No` = the agent is told and goes on without it |
| `factory:start` | factory, when the agent proposes a run (`orch factory propose`) | `Start` · `Edit` · `Not now` | `{"order": "t_…", "file": "proposals/<order>/p<N>.json", "hash": "<sha256>"}` | `Start` (a person) = the run may start; `Edit` = the agent asks what to change and proposes again; `Not now` = parked. Agent answers are ignored (factory/README.md, Authority) |
| `factory:autopilot` | factory, for an autopilot proposal | `Start` · `Edit` · `Not now` | `{"order", "file", "hash", "days": 1 \| 3 \| 7}` | `Start` (a person) = a grant for `days`, only for the proposal's `may_decide` |
| `factory:change` | factory, when the owner asks for more during a run | `Accept` · `Edit` · `Save for later` | `{"order", "file": "changes/<order>/c<N>.json", "hash"}` | `Accept` = added to the run; `Save for later` = a new idea |
| `factory:stop` | factory, at a stop of the line | ship: `Ship it` · `Send back`; else `Continue` · `Send back` | `{"order", "file": "stops/<order>/s<N>.json", "hash", "stage": "<stage>"}` | `Ship it` / `Continue` = go on; `Send back` = back to the stage with the comments as tasks |

Rules: an add-on acts only on answered questions of its own prefix, at most once per question (it records the question id
it handled in its own state); `action` holds ids and short summaries, never secrets or commands to run.
