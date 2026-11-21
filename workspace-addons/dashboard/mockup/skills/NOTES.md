# Skills (Preview add-on, ORCH-834)

- skills.html: the dashboard shell around the Skills add-on's own page. It runs the add-on's real script
  (`workspace-addons/skills/src/orch_skills/web/skills.js`) on `demo/api/page`, so the mockup and the product can not
  drift. Open from a static server rooted at the repo.
- Demo data: 12 skills from all four places (orch, this workspace, shared by the admin, your computer), 4 instruction
  files, 3 connected services, 2 logins; 4 need a look, 3 are off ("Codex still sees it" where it applies).
- The owner picked draft A on 19 Nov 2026 (one list with tabs, a switch per row, a side panel). Edit (ORCH-840): this
  workspace's skills (a form for the header, the steps as text) and instruction files (one text) open in the panel;
  `demo/api/item/<edit id>` feeds it. Save needs the dashboard, so in the mockup it says so. Delete with a bin and
  New skill follow in ORCH-841.
- Looks come from the master: `.switch-table`, `.list-tools`, `.facts`, `.sheet-actions` in widgets.css (gallery:
  Content, Switch list).
