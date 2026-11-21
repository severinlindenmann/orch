# Skills (Preview add-on, ORCH-834, ORCH-842)

- skills.html: the dashboard shell around the Skills add-on's own page. It runs the add-on's real script
  (`workspace-addons/skills/src/orch_skills/web/skills.js`) on `demo/api/page`, so the mockup and the product can not
  drift. Open from a static server rooted at the repo.
- Demo data: 12 skills from all four places (orch, this workspace, shared by the admin, your computer), 4 instruction
  files, 3 connected services, 2 logins; 4 need a look, 3 are off ("Codex still sees it" where it applies).
- The owner picked draft A on 19 Nov 2026 (one list with tabs, a switch per row, a side panel). Edit, delete with a
  bin and New skill follow in ORCH-840 and ORCH-841; until then the panel shows only Turn off / Turn on.
- Looks come from the master: `.switch-table`, `.list-tools`, `.facts` in widgets.css (gallery: Content, Switch list).
- ORCH-842: Logins are key profiles with a switch (per workspace; the panel says what off means); connected services
  show their sign-in state with Check sign-in; a shared skill has Remove from here, a removed one Get it back and
  "Your admin has a newer version"; the Codex limits are said in the panel. Demo: 13 skills, 3 logins.
