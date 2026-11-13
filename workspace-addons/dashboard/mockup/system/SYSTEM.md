# orch shared visual system

A calm workspace with enough information to make the next decision. Bring back old core's aligned rows, darker navigation, restrained cards and useful side panels. Keep the owner's plain language and remove technical decoration.

## Files and use

- `system.css`: standalone tokens, primitives, shell, states, result frames, motion and responsive rules. No imports or dependencies.
- `shell.html`: reusable app chrome with an intentionally empty `<main id="content" class="page">`. Copy the shell; set the active route's `aria-current="page"`. Its empty canvas is an integration slot, not a product empty state.
- `components.html`: complete visual reference with local examples, native controls, density switch, typed previews and Loaded / Loading / Empty / Error controls.
- `motion.html`: explicit Replay demos; all motion is idle until requested.
- `sample-*`: offline fixtures for the preview gallery. They are illustrative content, not product data.

Area pages use `<link rel="stylesheet" href="../system/system.css">`. Copy the same sidebar and topbar from shell.html. Do not change global tokens in an area stylesheet. Retain existing `btn`, `primary`, `outline`, `ghost`, `card`, `card-h`, `card-row`, `badge`, `chip`, `skeleton`, `nav-item`, `eyebrow`, `meta`, `page`, `topbar`, `sidebar`, `workspace`, `ws-switch`, `wsb`, `avatar`, `columns`, `stepper`, `ticket-stepper`, `progress`, `input`, `tabs`, `switch`, `menu`, `menu-pop`, `dialog`, `sheet` names. New classes describe their purpose rather than a page-specific appearance.

For the eventual restyle, load system.css after today's kit and page CSS, then remove conflicting page overrides rather than escalating specificity. This is a shared foundation, not a guarantee that every old page-specific selector has been replaced. New mockups only need system.css and their own layout rules. Never import the existing nested kit on top of this file.

## Token contract

| Role | Token / value | Rule |
|---|---|---|
| Canvas / navigation | `--bg #101216`, `--sidebar #0c0e11` | Navigation recedes; work remains central. |
| Card / raised / hover | `--surface #181b20`, `--surface-2 #20242b`, `--surface-3 #2a3038` | Cards are flat, overlays are raised. |
| Divider / interactive border | `--border #30363f`, `--border-strong #79838f` | Quiet dividers do not identify controls. Inputs use the strong border. |
| Text | `--text #edf0f3`, `--text-muted #b2bac5`, `--text-faint #a0aab6` | Primary, supporting, metadata. Never lower opacity for metadata. |
| Action | `--brand #61d5b8`, `--on-brand #092b23` | One teal accent; dark label on filled teal. |
| Working | `--working / --info #8fbef5` | Blue, `◉ Working`. No looping live dot. |
| Needs you / review | `--needs-you / --review / --warning #e5be72` | Amber, `! Needs you` or `◇ Ready for review`. Distinct words and symbols. |
| Done | `--done / --success #98cda3` | Green, `✓ Done`. |
| Paused | `--paused / --text-muted` | Neutral, `Ⅱ Paused`. |
| Failed | `--failed / --danger #f3a3a5` | Rose, `× Failed`; include a plain next action. |
| Type | 12/16, 14/18, 14/20, 20/28, 28/36 px | Metadata, compact body, body, section, page title. Four font sizes. |
| Weight | 400 / 500 / 600 | Normal, emphasis, heading. No bold wall of text. |
| Spacing | 2, 4, 8, 12, 16, 24, 32, 40, 48, 64 px | Use scale for padding and gaps; 1 px borders are not spacing. |
| Shape | 8 px controls, 10 px cards, 12 px dialogs, round status pills | No nested rounded boxes for ordinary rows. |
| Elevation | `--lift-shadow`, `--shadow` | Menus, toast, dialog and sheet only. |
| Density | `--row-height:40px`, compact 32 px; `--card-padding:16px`, compact 12 px | Comfortable default, apply view-wide. |

Semantic hues are bounded to neutral, teal, blue, green, amber and rose. Status colours have similar perceptual lightness (Lab L* about 74–80), with matching dark fills. Do not introduce purple review, orange add-on labels or rainbow workspace navigation. Data charts reuse these colours with direct labels, never colour alone (BP-09, BP-12–17).

Computed sRGB contrast, before browser rendering: primary text on the lightest surface **11.63:1**, supporting **6.79:1**, quiet **5.65:1**; input border **3.46:1**; focus teal **7.42:1**; teal button label **8.48:1**; working / needs / done / failed badge pairs **6.65 / 7.25 / 6.81 / 6.73:1**. All normal text pairs exceed 4.5:1 and interactive boundaries exceed 3:1. Decorative card dividers are deliberately softer, since content grouping is also supplied by spacing and surfaces. Recheck contrast whenever introducing another background.

## Shell and navigation

One inverted L: sidebar plus topbar, at most one contextual detail panel (BP-02). Sidebar is 232 px at 1280 and 1920. Below 1280 it becomes a 64 px icon rail. Icons have accessible names and focus labels; nothing is mouse-only. The workspace switcher and ticket views use native disclosures, including a popout on the rail. The phone switch has an accessible full label. At short heights the nav can scroll; the page never needs a forced desktop minimum width.

Four core links: Home, Tickets, Notes, Chat. Add-ons are a labelled native disclosure containing Automation, Focus, Insights, Sync, Shared links, Phone & workspaces. Settings is anchored at the bottom. This preserves the requested full route map without eleven undifferentiated top-level destinations (BP-50). Add-ons begin expanded for discovery. The additional Ticket views disclosure contains Needs me, Working now, Done this week (BP-21). In the application, persist the user's disclosure preference; these static pages deliberately do not store anything.

Only Home carries an attention count. Do not give every destination a badge. A ticket view query (`?view=needs-you`, `?view=working`, `?view=done-week`) is the proposed area contract. The board designer must implement those queries; the links are integration targets, not local filter implementations.

**Phone & workspaces lives under Add-ons.** It manages devices and workspace access. The bottom sidebar switch “Send questions to my phone” is a quick control, not a navigation shortcut. Settings contains notification preferences and the timeout, saved in place. Never give Settings a tab that silently redirects. If a Settings section needs device management, show an explicit link “Manage devices in Phone & workspaces →” while leaving the Settings section open (BP-47–49).

Topbar: current location and Ask the helper / New ticket. These are navigation actions. Inside a decision view, make the decision its sole prominent action and style global New ticket as outline. Breadcrumbs only for nested pages: Tickets › Customer survey; current location is not a link (BP-24, BP-51). Demo new-ticket links use `../board/board.html?new=1`; area authors should wire that query to their composer. The shell intentionally has no active route until it is adopted by an area.

## Layout at both desktop sizes

| Viewport | Sidebar | Page gutter | Reading layout | Work views |
|---|---:|---:|---|---|
| 1280×800 | 232 px | 24 px | 1000 px available; main + 296 px panel + 24 px gap | Board/table use all available width. |
| 1920×1080 | 232 px | 32 px | Content max 1280 px, centered; 320 px panel | Board/table/analytics `.page.wide` use available width. |
| 900–1279 | 64 px rail | 24 px | Panel 256 px; 16 px gap | Controls wrap; never squash text to 11 px. |
| Under 900 | 64 px rail | 16 px | Context panel stacks below content | Local table overflow allowed; no body overflow. |
| Under 600 | 64 px rail | 16 px | Single-column cards and previews | Topbar wraps and stops being sticky. |

Use `.columns` for story + properties; `.grid-2` for equal samples; `.grid-3` for three short units; `.grid-2.grid-wide-3` moves to three columns at 1600+. Do not add a third story column just because the screen is wide. Prose is capped at `76ch` using `.reading`, below the ~90-character ceiling. A board may retain five status columns when each fits at least 180 px; otherwise use a local horizontal board track or switch to the list, never body overflow. Every column has a count; empty columns say “None” (BP-01, BP-20).

For ticket lists use `.page.list-page`, a one-line header, one 32 px toolbar, 8 px gaps, a 32 px table head, then 40 px rows. Budget at 1280×800: 56 chrome + 16 top pad + 36 heading + 8 + 32 toolbar + 8 + 32 table head + 15×40 rows = **788 px**. Extra subtitles or banners reduce that capacity; put the summary beside the title and don't stack filter bars. Compact gives 32 px rows. The shared gallery demonstrates the row sizes with four representative rows; the consuming list must validate the fifteen-row target (BP-04, BP-82).

## Components and usage

- **Buttons:** `.btn.primary` for the next decision; `.outline` for alternatives, `.secondary` for a low-emphasis filled action, `.ghost` for details, `.danger` only for a named destructive action. Default 36 px; sm 32, xs 24, lg 40. Icon buttons require a full accessible name. At most three toolbar actions before selection (BP-11, BP-23, BP-76).
- **Inputs:** persistent label, hint underneath; `aria-invalid` and `aria-describedby` for errors. Placeholders never replace labels. Native select / checkbox / radio are deliberate. A checkbox styled `.switch` represents a boolean preference.
- **Segments / tabs:** segments switch a view or local setting; tabs switch a section within the same context. Native radio segments work without script. Real tabs need `tablist`, `tab`, `tabpanel`, selected state, roving focus and arrow keys, as implemented in motion.html. A section-link nav remains ordinary links (components.html).
- **Status:** one status phrase per unit, never the same status in header, banner and footer. A board column can supply the status label to its cards; do not repeat it just to add colour. A standalone card uses the labelled badge. Owner, one time fact and an optional preview complete the card. No IDs or technical chips.
- **Rows versus cards:** use rows for a collection, cards for a result preview, a decision or a genuinely separate group. Rows share one outer frame, not a card per line. Cards have no shadow. Compact applies to cards as well as rows. Use `data-density="compact"` on the view or native radios inside `.density-scope`.
- **Avatars / helper chips:** initial or helper symbol plus visible name. A lone initial does not identify responsibility. No decorative stacks of avatars.
- **Progress:** known steps use a labelled count and 4 px bar, or the four-stage stepper. Do not invent percentages for open-ended work. Announce meaningful stage changes, not every tick. Long jobs show elapsed time, current action and Leave running / Cancel (BP-63).
- **Side panel:** editable owner, due and definition of done. Keep extra properties under one Details disclosure. Production edits save immediately, with rollback on failure and Undo where appropriate (BP-28).
- **Menus / tooltips:** native details for simple menu disclosures; normal links/buttons retain natural keyboard navigation. These are not ARIA application menus. Close on Escape as shown; application click-away handling may be added. Tooltips only reinforce shortcuts, never explain a primary label.
- **Dialog / sheet:** native `showModal()` supplies focus containment, Escape dismissal and focus restoration; safe action gets autofocus. Do not nest dialogs. Use one sheet over the current ticket for preview; retain underlying scroll. Close immediately so dismissal never feels blocked.
- **Toast:** one visible at a time, 5 seconds for success, with Undo or Open for meaningful changes. Queue in the application; the reference replay replaces the previous demo toast. Error toasts persist until dismissed; blocking errors also stay by their source. Never disappear a focused toast action in the application: pause the timer while hovered/focused (BP-58).

## Information density rules

Two levels only. Level 1 answers “What is happening, why does it matter, what can I do?” Level 2 is one click away. Maximum seven facts per card/header, five KPIs. No nested Details inside Details (BP-18, BP-79–82).

| Page type | Visible at a glance | Behind one click |
|---|---|---|
| Home | Needs-you count, each item's title, reason, one action; working count. Needs-you first. | Finished work, full result, older history. All-clear includes last three finished items. |
| Board / list | Title, status, named person/helper, one update/ETA fact, attention reason when needed, at most one 64 px result thumbnail. | Description, steps, full file set, properties. A peek retains selected row and scroll. |
| Ticket detail | Title, status, who, next action, reason if blocked, elapsed/ETA. Story: request → steps → results → next step. | Raw timestamps, IDs, costs and logs in Details. History defaults to three events; completed steps one line each. |
| Focus | Current step, who is working, elapsed time, steps completed, latest result and the one action needed. | Full transcript, logs, older steps. Updates do not steal scroll; show “N new” when reading earlier work. |
| Insights | 3–5 meaningful KPIs with period deltas; 1–2 labelled charts; one shared time-range control. | Breakdown tables, individual helpers, raw values. No empty chart shell or fake zero. |
| Automation | What will happen, next time, on/off state, last outcome, action for a failure. | Schedule rule, older runs and advanced conditions. |
| Notes / chat | Note title or conversation, useful excerpt, author/helper, last change; the current message and reply action. | Earlier conversation, file collection, source details. Preview attached files in context. |
| Sync / Shared links / Phone & workspaces | Connection or sharing state, destination/person, last success, next needed action. | Storage path, technical connection facts, detailed history and advanced sharing options. Never put secrets in a preview. |
| Settings | Workspace name, helpers, notifications, dark appearance, access. Save feedback in place. | Technical and advanced settings in one disclosure per section. No redirecting tabs. |
| Results | Typed visual preview, name, type, size, age; Open / Download / Copy link. | Full viewer, source view, remaining files. |

## File and result previews (BP-30–37)

Every type gets a real, useful representation, not merely a filename. `.preview-body` reserves 192 px in the reference collection; area pages can use `aspect-ratio` for their known media dimensions. Board thumbnails are at least 64×64. One file gets a larger inline frame; more than six files gets six thumbnails plus a “+N more files” tile and a type filter. The reference gallery deliberately shows all types at once for inspection.

| Type | Preview | Full view / fallback |
|---|---|---|
| Image | Contained thumbnail, informative alt text | Sheet/lightbox; fit/zoom; Escape closes. SVG sample is local and contains no script. |
| PDF | Actual local PDF object, first page | Browser PDF viewer / download. Browsers without inline PDF show the summary and explicit fallback. Production uses a first-page thumbnail to avoid embedded browser toolbars. |
| HTML | Local page in `<iframe sandbox>` with no permissions | Full separate page; never allow scripts and same-origin together. Production content must remain isolated. |
| CSV / XLSX | Header, row numbers, column selector and rendered cells | Same frame for parsed XLSX. CSV parsing beyond 512 KB: partial rows + Download full file. XLSX parsing is an application responsibility. |
| Markdown | Rendered heading, paragraphs and list | One Show source disclosure; long documents can open separately. |
| Code / JSON | Highlighted tokens, line numbers and folded extra content | Full source one click away, wrap or local horizontal scroll. |
| Text | Wrapped monospace excerpt | Full text open/download. |
| Audio / video | Native controls with a local playable sample; duration | Browser-supported playback, no autoplay; unsupported codecs show download fallback. |
| Unknown / binary | Type glyph, name, size, age and explanation | Download; never an endless loader. |

Every preview uses **Open, Download, Copy link**, in that order, always visible and keyboard reachable; Share can follow when relevant. `file://` clipboard access varies, so Copy link announces a fallback if unavailable. In the app use stable share URLs rather than file URLs. A static single-file sheet demonstrates the frame; multi-file sheets must add previous/next buttons, Left/Right keys and a file position label, and preserve their state in the URL (BP-32, BP-54).

Above a 10 MB browser-render budget, show a bounded first-page/first-rows preview with an explicit partial-preview sentence. Limits are defaults to validate per renderer, not claims that every type uses the same parser. Failure keeps the same frame and says “Can’t preview this file” with Download. Do not expose raw renderer errors. Never insert untrusted HTML into the main document.

## Loading, errors and performance

The brief asks for shell + skeleton within 100 ms while the numeric checklist says not to show indicators for sub-second work. Reconcile by expected latency (BP-05, BP-55–67):

1. Cached/warm/local: retain content; commit the update immediately, no skeleton or spinner.
2. Known cold/slow route (expected >1 second): show persistent chrome and the correctly shaped skeleton within 100 ms. If latency is unknown and the request is still pending at 1 second, show the reserved loading frame then. Never flash an empty state first.
3. Initial large areas: skeletons match final row heights, card blocks, header lines and media ratio. Mark the region `aria-busy="true"`; hide decorative skeletons from assistive technology; give a polite loading/completion message. Use one coherent indicator per region, not a spinner in every card.
4. Module/action lasting 2–10 seconds: inline spinner within the same button width, with a visible “Saving…” label. Whole-page spinners are not an option.
5. Over 10 seconds: current step + elapsed or real determinate progress, and cancel/background action. Do not loop a skeleton for a helper's entire job.
6. Refresh: keep old data, refresh in place, quietly update “Updated … ago”. Do not blank the page, jump the scroll, or shimmer over existing results.
7. Empty is a settled response: explain what appears, how to start, and provide an action. Errors stay near the source with Retry; codes only in Details.

Production targets: local feedback <100 ms; warm route <300 ms; cold data route <1 s where practical; FCP ≤1.8 s, LCP ≤2.5 s, INP ≤200 ms, CLS ≤0.1. API reads p50 <150 ms/p95 <500 ms; small writes optimistic immediately with confirmation <1 s. Prefetch on focus/65 ms hover, skipping Save-Data and slow connections. Persist view, selection, filter and time range in the URL; restore scroll on Back. None of these runtime or network metrics is claimed as measured by this static deliverable.

## Motion contract (BP-69–74)

| Motion | Duration | Curve / rule |
|---|---:|---|
| Hover / press / toggle | 100 ms | `--ease-move: cubic-bezier(.4,0,0,1)`; press translates 1 px. |
| Menu / popover | 150 ms | `--ease-enter: cubic-bezier(0,.4,0,1)`; only enter. |
| Explicit first-page entry | 150 ms | Enter, 4 px travel + fade. Opt-in `.page-enter`, never on refresh. |
| Add / remove a row | 120 / 100 ms | Enter / exit; no stagger. Apply actual removal after exit; reduced motion removes instantly. |
| Tab switch | 0 ms | Immediate, preserve panel geometry. |
| Dialog / side panel | 200 / 240 ms | Enter; 8 / 24 px travel. Dismiss instantly. |
| Toast | 200 ms enter / 120 ms exit | Enter / `--ease-exit: cubic-bezier(.6,0,.8,.6)`. |
| Progress | 150 ms | Move; label changes immediately. |
| Status | 200 ms once | Subtle border pulse; no persistent movement. |
| Skeleton | 1600 ms | Low-contrast shimmer only under `[aria-busy=true]`. Instant content swap. |

**Conflict resolved:** the system brief explicitly requests a 150 ms page transition; BP-71 prohibits fading every route. The class and Replay example exist but are opt-in for first entry only. Routine navigation has no page fade. Skeleton-to-content and numbers never animate. A reorder in the real app should use FLIP on the moved item only (120 ms), not animate the entire list.

One focal animation at a time, no input blocked by animation. `prefers-reduced-motion: reduce` disables every transition, pulse, shimmer and transform animation; all controls still change state. No ambient movement at idle. The motion page's separate Replay controls are independent experiments, not an instruction to run every animation together.

## Accessibility and interaction contract

Skip link; semantic landmarks; ordered headings; named icon buttons; visible 2 px focus with 3 px offset; no clipped focus rings on ordinary cards. Native radio, checkbox, disclosure, select and dialog behaviours are intentional. Status has readable words and a symbol (BP-15, BP-75–77). Toolbar controls are normally 32–40 px, never below 24×24. No essential hover-only controls. In forced-colours mode, buttons/status boundaries and focus remain visible.

The consuming application must supply the full command palette and keyboard routes: Cmd/Ctrl+K toggles search, Escape closes, G-then-letter routes, ? shortcut help, arrows/J/K for lists, Enter opens (BP-52–54). The static shell does not advertise a search control that cannot work. Add shortcuts progressively and never intercept typing inside fields. URL persistence, optimistic updates, toast queues and multi-file viewer navigation are integration behaviours, not implemented backend features here.

## Copy rules

Sentence case. Familiar nouns: helper, step, result, file, needs you, ready for review. Actions name the outcome: “Accept result”, “Ask for changes”, “Download file”. No “OK”, “Submit”, raw IDs, branch names, vendor names or unexplained abbreviations in default content. If connection details genuinely require it, say “private network”, and keep technical explanation in Details. A primary label should never need a tooltip. Use one useful sentence before a long list (BP-08, BP-11, BP-78, BP-80–81).

## What changed vs today and why

- Larger page titles and consistent body text make the main point easier to find.
- Compact, aligned rows put useful work on screen without making text smaller.
- Cards group decisions and previews instead of putting every line in its own box.
- Status always has a word and a symbol, so colour is never the only clue.
- Teal marks actions; quieter status colours keep the whole page from competing for attention.
- Each work item shows who is responsible and one useful time fact.
- Files show real content, with the same three actions in every preview.
- Loading, empty and failed states look different and keep the same space.
- Phone & workspaces has one clear home; Settings no longer disguises a page jump as a tab.
- Short, optional motion explains changes, while reduced-motion settings are respected throughout.
- Wide screens get useful columns; reading lines stay a comfortable length.
- Technical details move one click away, leaving plain-language summaries in view.

## Validation and handoff

Reviewed the supplied screenshots, brief, checklist, old-core token source, current tokens/components/motion, current style/look/page styles and rendered HTML structure. No challenge findings or owner feedback files were present during this pass. Do not infer approval from their absence.

Static validation covers HTML structure/local references, JS syntax, CSS token references and calculated contrast. The manager must capture shell/components at 1280×800 and 1920×1080, check the rail at 1024 and stacking below 900, Tab through dialogs/previews, test reduced motion and measure the actual application's performance. No browser was run, and no runtime accessibility, CLS or Web Vitals pass is claimed. Area authors should cite BP rules above when diverging from the reference and keep the same tokens and chrome.
