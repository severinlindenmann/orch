# publish redesign notes

## publish.html — Shared links

- `?state=empty&server=none` (ORCH-2017): no publish server yet. One master empty state (no Share a file, which would only fail) with its one next step, Shared link settings (R7.2).
- The existing survey-results.html appears once, with HTML type, 319 bytes and a consistent expiry date (SN-11).
- Share a file is a clear primary action; stopping sharing names the file and asks once (SN-11; BP-48).
- Connection details move to add-on settings and the file gets a preview entry point (SN-03, SN-11).
- Product data: Needs actual private share URL, safe rendered file content, extend capability and expiry update API. The challenge supplies the filename, size and expiry but not the HTML or link; preview and copy explicitly report that gap. No invented URL, views or file contents.

### MOTION and performance
- First entry / Replay: content opacity, 150 ms, shared enter easing `cubic-bezier(0,.4,0,1)`; no stagger or travel. Settings tab swaps and skeleton replacement are instant. This reconciles the requested entry preview with BP-71 routine navigation guidance.
- Controls: hover 80–100 ms; switch thumb 100 ms with shared move easing. Details open: opacity and 2 px displacement, 150 ms enter; close instant. Dialog: shared 200 ms enter, instant dismissal and native focus containment. Saved/refresh status: one 200 ms pulse. Reduced motion disables all animations/transitions and leaves static skeletons (BP-69–77).
- Every route renders its own content-shaped skeleton: an inert, hidden-from-accessibility clone retains the exact row/card geometry. Query `?state=loading` is applied before body paint; Loaded / Loading / Empty / Replay work locally. Loaded content is preserved during the Refresh demo; only its status changes (SN-03, SN-22–24; BP-61–64).
- Targets, not measured results: route shell+skeleton ≤100 ms; warm full paint <300 ms; cold data <1 s; FCP ≤1.8 s; LCP ≤2.5 s; INP ≤200 ms (local target <100 ms); CLS ≤0.1. Reserve content geometry and cache by route/workspace. Replace serial CLI startup in `/api/state` with one in-process snapshot; read independent data in parallel. Publish view and links must not waterfall. Background refresh must not clear cached content. Prefetch after 65 ms hover/focus when data-saving allows (SN-03, SN-04; BP-59–67).

### Shared-system and scope notes
- Shell sidebar and topbar are copied from `home/home.html`; only current route and breadcrumb change. The shell's grouped add-ons are retained rather than proposing a second sidebar. Owner's explicit real Settings phone tab overrides SYSTEM.md's conflicting device-management guidance. No system/base files were edited.
- Local CSS additions: settings column and vertical tabs, setting rows, permission grid, content-shaped loading masks, file rows, error recovery. Preview controls use the shared collapsed pill. Existing system tokens/components provide colour, type, focus, buttons, cards, dialogs and motion. No new global tokens. Request these layouts as shared components if adopted.
- At 1280: 184 px Settings navigation plus flexible content; at 1920: 200 px navigation within the shared 1280 px content cap. Activity uses the available width with a 296/320 px context column. Below 1000, actions wrap; below 600, settings sections stack. Text stays at shared sizes, never shrinks to fit (SN-14, SN-25; BP-01–05).
- No network, dependencies, fonts or browser runs. All mutations are explicitly local previews; forms cannot pair, install, send or share. Empty General/add-on detail repeat saved settings because those are not empty collections. “Updated just now” follows the shared mockup header; Refresh demonstrates retained content, not a server fetch.
- Validation: parsed all HTML, checked unique IDs and ARIA targets, checked local assets and JavaScript syntax. Browser screenshots, measured performance, contrast rendering and keyboard interaction remain for manager review; no claim of a full automated BP pass.

Shared-system fix requested: `input.switch` needs explicit 36 × 24 px dimensions because the shared generic checkbox selector has greater specificity than `.switch`. Applied locally.

### Consistency pass

- Copied the Home sidebar, including Home badge 3 and its phone toggle; marked the relevant destination current (none for an unknown page).
- Aligned title/subtitle headers and “Updated just now”, New ticket links, and generic “Your helper” wording.
- Removed local preview-bar markup, CSS and event handlers; loaded `../system/preview-controls.js` after page scripts. Query-driven loading/empty views and skeletons remain; entry and Replay now use shared motion with reduced-motion support.

## Revised after the owner's comment (13 Nov)

### publish.html
- Expiry now appears once in the link row; the repeated Details block is removed.
- Removed the “One link, one file” panel and its empty separator, leaving a short explanation beneath the list.
- Each desktop row shows the file name, who can open it, expiry and actions on hover or keyboard focus; touch and narrow screens keep actions visible.
- Kept the supplied survey-results.html data, stop-sharing confirmation, loading and empty states, shared shell, Preview pill and motion.
- Checked the page for duplicate information and stray separators, and checked loaded/loading/empty layouts at 1280, 1920 and 390 px without horizontal overflow.

## Revised after the owner's comment (13 Nov)

### publish.html

- Reviewed the whole page: it already has no Details or Technical details disclosures, so no layout change was needed.
- Preserved the earlier single shared-file row, expiry, actions, shared Preview pill, loading and empty states, and motion.



## Revised after the owner's comment (13 Nov)

### publish.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### publish.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.

- Share a file (e2e 15 Nov): the window stays open after Create link, shows the link with a Copy button and says "Copied" (the link is copied once automatically). A ticket file's viewer has "Share by link…" next to "Copy link", only when sharing is on; it opens this same window for that file.

## RP2 and RP7 (ORCH-2170, 26 Nov)

- Title "Publish" (RP8 B). Each row: file, your note (or "No note"), the ticket and "Ends in N days"; a link that ends within a day gets a warning chip ("Ends tomorrow"). The line below says orch checks each file for passwords first.
- `?state=connect`: not connected yet. The page is the paste box (the admin's whole text, Connect, one inline sentence when no connect line is found); the heading shows "Not connected yet" instead of Share a file.
- `?state=offline`: publish can't be reached. The rows come from this workspace's record (the fallback label is “From this workspace’s record” when no date is known), a banner says what that means, and Share a file, Copy link, Extend and Stop sharing wait (disabled).

## Rows fit a phone (ORCH-2213, 28 Nov)

- The "Shared now" rows are the master `card-row` (file name, note, then ticket and end on one line; the buttons in `actions`). They wrap by themselves, so nothing is cut at 390 and 320 px, also in `?state=offline`. The old mockup-only row grid is gone from `mockup.css`; the buttons are always visible, as in the product.

## O-25 (owner 28 Nov): a shared file beside the panel

- publish.html: a shared file is its name and note, then the ticket and "Ends in …"; in a page area under 900 px the
  buttons sit on a line of their own under the text, as whole buttons that wrap (never a word broken letter by
  letter). On a wide page they stay at the right of the row.
- See it: narrow the window under 900 px, or open `publish.html?room=617` and `?room=785`.
- "Stop sharing" in the danger colour is W-058f (another batch).
