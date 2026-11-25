# Skills (Preview add-on, ORCH-834, ORCH-842)

- skills.html: the dashboard shell around the Skills add-on's own page. It runs the add-on's real script
  (`workspace-addons/skills/src/orch_skills/web/skills.js`) on `demo/api/page`, so the mockup and the product can not
  drift. Open from a static server rooted at the repo.
- Demo data: 12 skills from all four places (orch, this workspace, shared by the admin, your computer), 4 instruction
  files, 3 connected services, 2 logins; 4 need a look, 3 are off ("Codex still sees it" where it applies).
- The owner picked draft A on 19 Nov 2026 (one list with tabs, a switch per row, a side panel). Edit (ORCH-840): this
  workspace's skills (a form for the header, the steps as text) and instruction files (one text) open in the panel;
  `demo/api/item/<edit id>` feeds it. Save needs the dashboard, so in the mockup it says so.
- ORCH-841 adds Delete in the panel (this workspace's and your computer's skills), the Bin tab with Restore (3 demo
  entries, one that cannot be restored because a skill of that name is back) and New skill.
- Looks come from the master: `.switch-table`, `.list-tools`, `.facts`, `.sheet-actions` in widgets.css (gallery:
  Content, Switch list).
- ORCH-842: Logins are key profiles with a switch (per workspace; the panel says what off means); connected services
  show their sign-in state with Check sign-in; a shared skill has Remove from here, a removed one Get it back and
  "Your admin has a newer version"; the Codex limits are said in the panel. Demo: 13 skills, 3 logins.
- ORCH-1819: Connected services also lists the servers of enabled Claude plugins and of the Copilot CLI file
  (read-only rows: "Manage in Claude" / "Manage in Copilot CLI", no switch), and the services in the Claude account
  that Check sign-in found ("In your Claude account", kept from the last check). The tab says "Connected services
  (MCP servers) your helpers can use" and "Last checked …". Demo: linear (plugin), github (Copilot CLI), Gmail (account).
