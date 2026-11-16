# Developer skills

Skills for helpers that build orch itself (this repo), not for orch users. orch never installs them into a user's
workspace; the shipped skills live in `workspace/skills/` and the add-ons. The orch development workspace links its
`.agents/skills/<name>` to these folders, and helpers working in a copy of this repo find them here.

- `orch-design-system`: the one master component library and style guide (R6).
- `orch-mockup`: the mockup, the visual source of truth (R6.3).
- `orch-ux-checklist`: the UX/UI checklist every UI change passes (R7.6), with its research and a worked example.
