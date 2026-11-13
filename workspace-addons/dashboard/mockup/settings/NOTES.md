# settings redesign notes

## settings.html — General

- Workspace name, description and appearance come first; folder paths sit behind Details (SN-08, SN-15, SN-17; BP-49, BP-79).
- Phone, helper, shared links and sync are compact summaries with direct destinations (SN-08, SN-13, SN-16).
- Advanced groups team sharing, finished-work policy and copies; edits save locally with visible feedback (SN-18; BP-48).
- Product data: Needs rename, appearance and policy write endpoints, current helper label, share count and cache timestamps.

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

## settings-helper.html — Helper

- Unavailable helpers offer setup guidance instead of a misleading Test action (SN-19).
- Your own helper uses a human label; existing Claude and Codex unavailable states are preserved (SN-19; BP-78).
- Permission choices use a visible radio and strong teal selection; Full explains its consequence (SN-20; BP-13, BP-77).
- Product data: Needs installation capability and authoritative permission value. Auto is a proposed preview default; not verified in the provided snapshot. Tests and installation cannot run in static HTML.

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

## settings-phone.html — Phone & workspaces

- Phone setup is a real keyboard-accessible Settings tab; it never opens the messages route implicitly (SN-01, SN-14; BP-47, BP-77).
- Pairing, delivery switch and 12-hour timeout share one place (SN-10, SN-13).
- Connected status and zero allowed workspaces match the supplied data; Open messages is an explicit link (SN-10, SN-24).
- Product data: Needs paired-device list, short-lived pairing token/QR, access grants, permission checks and connection freshness. No paired phone is a proposed empty fixture: snapshot did not expose device data. Pairing opens an honest unavailable preview rather than a fake scannable code.

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

## settings-addons.html — Add-ons

- Six installed optional add-ons become aligned rows, using sidebar names (SN-09, SN-26).
- The always-on dashboard is reduced to a footnote, freeing space for useful controls (SN-09).
- Add an add-on opens a catalogue state; no imaginary products or installation results are shown (SN-09; BP-55).
- Product data: Needs catalogue availability, friendly labels, install progress and per-add-on configuration. All six existing optional add-ons are On; empty preview represents a fresh installation.

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

## addon-detail.html — Shared links add-on settings

- An add-on has one focused settings surface and a clear return to Installed add-ons (SN-09, SN-26).
- Connection address is one click away; connection status stays visible (SN-26; BP-49).
- One shared-file summary links to the actual list, without repeating files (SN-11).
- Product data: Needs connection status, permission-aware writes, share count and cached update time.

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

### settings-phone.html
- Pairing stays in Settings and uses the relay connection; it does not open the relay server.
- Relay status, address, Set up relay and Reconnect now come before the phone controls, with “Your phone talks to this workspace through your relay.”
- Empty shows no relay, a disabled Pair a phone button and “Connect to your relay first”; `?relay=disconnected` shows the reconnect case.
- Setup and reconnect demonstrate enabling pairing locally; no real connection is made.

### settings-phone-pair.html
- Added the pairing dialog open over the Phone & workspaces tab, with the relay address and QR code.
- The QR encodes demo text and is clearly marked as a preview; a real pairing token must come from the connected relay.
- Close and Escape return to the tab; loading and empty previews keep their appropriate tab states.

### settings.html
- Restored an icon picker and named colour swatches with immediate previews in the sidebar and editor; Save keeps the choice for this page session and Cancel restores it.
- Folder now shows Demo plainly, offers Copy path, and keeps the full path in a disclosure below the name.
- Checked all General rows for consistent label, value and action columns, including the empty preview and narrow screens.

### settings-helper.html
- Updated their embedded General and Phone panels so switching tabs shows the same revised controls.
- Retained the shared shell, Preview pill, loading and empty views, keyboard tabs and reduced-motion support; helper labels use plain names.

### settings-addons.html
- Updated its embedded General and Phone panels so switching tabs shows the same revised controls.
- Retained the shared shell, Preview pill, loading and empty views, keyboard tabs and reduced-motion support.

Validation: browser checked the four reviewed routes at 1280, 1920 and 390 px in loaded, loading and empty states with no horizontal overflow. Exercised icon/colour preview and Save, tab switching, pairing, and empty relay setup. QR is a local demo asset, not a real pairing credential. These changes replace the earlier note about an unavailable pairing dialog.

## Revised after the owner's comment (13 Nov)

### addon-detail.html

- Removed both Details toggles, including the empty preview; connection status and switches stay visible.
- Moved the existing connection address into a small, always-visible About this add-on section at the bottom. No version or maker was supplied, so neither is invented.

### settings.html

- Show the full folder path as quiet text beside the existing Copy path action; if copying is unavailable, the path is selected for manual copying.
- Show sharing and finished-work settings in an ordinary card, with no Advanced disclosure; preserve the icon and colour picker.

### settings-helper.html

- Updated the embedded General panel to show the folder path and sharing settings without disclosure triangles.
- Kept helper choices, permission controls, and the earlier phone setup revisions intact.

### settings-addons.html

- Updated the embedded General panel to show the folder path and sharing settings without disclosure triangles.
- Kept the installed add-ons list, switches, and earlier phone setup revisions intact.

### settings-phone.html

- Updated the embedded General panel to show the folder path and sharing settings without disclosure triangles.
- Kept relay setup, reconnect, pairing, and the disconnected preview intact.

### settings-phone-pair.html

- Updated the embedded General panel to show the folder path and sharing settings without disclosure triangles.
- Kept the pairing dialog, demo QR code, and its loading and empty behavior intact.



## Revised after the owner's comment (13 Nov)

### addon-detail.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### settings-addons.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### settings-helper.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### settings-phone-pair.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### settings-phone.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### settings.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### addon-detail.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Phone pairing now has a working demo confirmation and a phone question preview; cancel leaves questions off.

### settings-addons.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Phone pairing now has a working demo confirmation and a phone question preview; cancel leaves questions off.

### settings-helper.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Phone pairing now has a working demo confirmation and a phone question preview; cancel leaves questions off.

### settings-phone-pair.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Phone pairing now has a working demo confirmation and a phone question preview; cancel leaves questions off.

### settings-phone.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Phone pairing now has a working demo confirmation and a phone question preview; cancel leaves questions off.

### settings.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Phone pairing now has a working demo confirmation and a phone question preview; cancel leaves questions off.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.
