# Skills (Preview add-on, ORCH-834)

- skills.html: the dashboard shell around the Skills add-on's own page. It runs the add-on's real script
  (`workspace-addons/skills/src/orch_skills/web/skills.js`) on `demo/api/page`, so the mockup and the product can not
  drift. Open from a static server rooted at the repo.
- Demo data: 12 skills from all four places (orch, this workspace, shared by the admin, your computer), 4 instruction
  files, 3 connected services, 2 logins; 4 need a look, 3 are off ("Codex still sees it" where it applies).
- The owner picked draft A on 19 Nov 2026 (one list with tabs, a switch per row, a side panel). Edit follows in
  ORCH-840. ORCH-841 adds Delete in the panel (this workspace's and your computer's skills), the Bin tab with
  Restore (3 demo entries, one that cannot be restored because a skill of that name is back) and New skill.
- Looks come from the master: `.switch-table`, `.list-tools`, `.facts` in widgets.css (gallery: Content, Switch list).
