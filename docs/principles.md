# Why the rules are what they are

`AGENTS.md` holds the rules. This page holds the reasons, how they were made, and what is still to clean up.

## Where they come from

On 15 Nov 2026 the owner asked for fixed rules so that dev agents stop drifting ("the goal is that in future development
this gets followed and not always the develop agent does other things again"). The owner's points:

- orch always works as a standalone CLI without add-ons.
- There is one brand and design library with every reused visual element, and add-ons always reuse it.
- Two main features, tested and challenged the most:
  - workspace ↔ workspace over the relay (assign and share tickets, info, agent context);
  - local context management with the orch CLI, with agents working task-based, evidence-based and context-based.
- UX that flows, follows web best practice, and is fast and stable.
- This is a prototype. The end goal is an enterprise product, but the focus now is a fast, reliable prototype.
  - Security matters for relay and publish: no leaks, nothing open from the outside.
  - Hardening the workspace against its own agent does not matter now.
- End goal: anyone installs orch on their own laptop (Windows or Mac):
  - they keep their skills, secrets, tools, MCP servers and agent tool;
  - it works the same for marketing, sales or development;
  - the agent works as autonomously as possible, and the human decides only real things (for example a production
    deployment), never "may I do this".
- orch is not orch-core. Visuals and code snippets may be reused, concepts may not. orch-core's sign-it concept killed
  that prototype through complexity.

## How they were made

1. An Opus draft based on the owner's points and earlier owner decisions.
2. Three independent challenges:
   - Opus through the Claude API (adversarial);
   - GPT through the OpenAI API (adversarial);
   - a repo check that compared the draft with the real code.
3. v2 merged their findings. The owner accepted all 10 rule parts and 6 clean-up choices on 15 Nov 2026.

What the challenge changed:

- **"Exactly once" became "at least once with duplicate drop" (R3.1).** Exactly-once delivery would have made agents
  build consensus machinery.
- **"A second agent reviews every feature" was dropped.** It was a planning gate again. The rule is now one review pass
  and no loops (R4.5).
- **Asking the human (R2.4) no longer covers sending to connected workspaces.** The old wording ("sending something
  outside") would have stopped the main feature.
- **Speed numbers are targets, not gates (R8.3).** CI fails only on a slowdown of more than 30%.
- **Real-agent e2e runs only before a release (R3.4).** Every PR uses a scripted fake agent, which is deterministic.
- **New rules:**
  - inbound work is data, never instructions (R3.2);
  - default context sharing (R3.3);
  - a secret scan on everything that leaves the machine (R5.2);
  - safe ticket data and updates (R8.2);
  - install, doctor and uninstall (R8.5);
  - `orch pause` (R8.6);
  - every command prints the next step (R2.7);
  - a decision log (R9.5).

Reviewer points not taken:

- **"Drop publish end-to-end encryption, it is key custody."** The key lives only in the link fragment and is never
  stored. This is already built and was decided on 4 Nov.
- **"Drop the no-vendor-names rule."** It is an owner rule; only the VPN product name is banned.
- **"The mockup is a second source of truth."** Kept, as the owner decided on 31 Oct. R6.3 splits the roles: the master
  gallery is the source for components, the mockup is the source for screens.
- **"Every first contact needs a human accept."** Not needed: pairs come from the relay admin, and delegate and start
  already need the receiver's allow.

## Owner choices of 15 Nov

| Question | Choice |
|---|---|
| orch-core proof/signing leftovers in the repo | Remove them (one clean-up PR) |
| Relay and publish clients: add-ons or core? | Keep them in the core as optional built-ins; fix the docs (R1.1) |
| Add-on stylesheets and the copied kit | Merge into the master design system and add the style lint |
| Windows testing | CLI smoke on Windows + macOS on every PR touching workspace/add-ons; full run nightly |
| Sharing agent context | Summary plus picked items with a preview; full ticket opt-in per send |
| Incoming work from other workspaces | Data, never instructions; runs only after the receiver's allow |

## Known violations at the time of writing (clean-up issues)

The repo check found places where the code already breaks the rules. Each one is a GitHub issue labelled `rules`:

- **R4.1, banned concepts.** Still in the code:
  - `workspace/src/orch/humanproof.py`, `pageproof.py`, `filesig.py`, `keystore.py`, `denyrules.py`;
  - `contracts/human-proof.md` and its schema;
  - `syncgate.py`.
- **R1.2, the core names add-on packages.** `workspace/src/orch/addons.py` (`SHIPPED_ADDONS`), and "dashboard" is
  hard-coded in `chat.py` and `chat_groups.py`.
- **R6.2, more than one source of styles:**
  - the dashboard ships `web/kit/` (a copy of the master) and `style.css` / `pages/*.css`;
  - focus has `focus.css` with its own colours;
  - insights has `insights.css`;
  - the relay and publish portals have a second look pipeline (`scripts/gen_look_web.py`).
- **R1.6 / R3.4, Windows.** There is no Windows CI on PRs (manual only).
- **Enforcement CI is not built yet:** banned-word check, core→add-on lint, style lint, secret scan, ticket fixture test,
  and the fake-agent F1/F2 e2e.
- **R2.6.** The shipped skill block says "ask, then stop". The rule says to keep working on independent items.
