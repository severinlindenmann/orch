// Playwright check of the admin portals (LOOK-5): pick an icon before connect -> badge shows;
// after the workspace chose its own look -> picker gone, 409 text shown. Usage: node look_portal_check.mjs <kind relay|publish> <adminUrl> <token> <wsId> <wsName> <workspaceTokenForPatch> <publicUrl>
const { chromium } = await import(process.env.PW_DIR + "/playwright/index.mjs");
const [kind, base, token, id, name, wtok, pub] = process.argv.slice(2);
const b = await chromium.launch();
const ctx = await b.newContext();
await ctx.addInitScript((t) => { try { sessionStorage.setItem("orch_admin", t); } catch (e) {} }, token);
const page = await ctx.newPage();
const fail = (m) => { console.error("FAIL " + m); process.exit(1); };
async function openEditor() {
  await page.goto("about:blank");
  await page.goto(base + "/admin#" + (kind === "relay" ? "overview" : "workspaces"));
  if (kind === "relay") {
    await page.waitForFunction(() => typeof workspaces !== "undefined" && workspaces.length > 0);
    await page.evaluate((i) => workspaceSheet(workspaces.find((w) => w.id === i)), id);
  } else {
    await page.locator(`[data-edit-id="${id}"]`).click();
  }
  await page.locator("[data-look-row]").first().waitFor({ timeout: 10000 });
}
await openEditor();
console.log('rows', await page.locator('[data-look-row]').count(), 'dialogs', await page.locator('dialog').count());
await page.locator('.look-picker [role="option"][aria-label="Wallet"]').first().click();
await page.getByText("Saved.").first().waitFor({ timeout: 5000 });
const r = await fetch(base + "/admin/api/workspaces" + (kind === "relay" ? "" : ""), { headers: { "X-Orch-Admin": token } });
const w = (await r.json()).items.find((x) => x.id === id);
if (w.icon !== "wallet" || w.look_by !== "admin") fail("admin pick not stored " + JSON.stringify(w));
if (!(await page.locator("[data-look-row] .look-badge").count())) fail("no badge");
// the workspace takes over
const m = await fetch((pub || base) + "/v1/me", { method: "PATCH", headers: { "X-Orch-Workspace": id, Authorization: "Bearer " + wtok, "Content-Type": "application/json" }, body: JSON.stringify({ icon: "house" }) });
if (m.status !== 200) fail("workspace patch " + m.status);
await openEditor();
if (await page.locator('.look-picker').count()) fail("picker still shown after connect");
await page.getByText("This workspace chooses its own icon.").first().waitFor({ timeout: 5000 });
console.log("OK " + kind);
await b.close();
