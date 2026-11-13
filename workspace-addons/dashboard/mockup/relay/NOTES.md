# relay redesign notes

## relay.html — Messages

- Messages are separate from pairing and access; Phone & workspaces remains the shell destination (SN-01, SN-10).
- The real zero-message state explains how to begin, with Open phone settings (SN-10; BP-55).
- The workspace column shows zero allowed workspaces and an explicit setup path (SN-10, SN-25).
- Product data: Needs cached message history, send permissions and allowed-workspace list. Loaded and empty are deliberately the same: there are no messages in the supplied data. No fictional messages are added.

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

### relay.html

- Reviewed the whole page: connection status and next steps are already visible without Details or Technical details disclosures.
- Preserved the existing messages and workspace empty states, Settings links, shared Preview pill, and motion.

