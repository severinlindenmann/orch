# Files and result previews — AFTER

Scope: only `previews/`. All 19 requested pages use `../system/system.css`, the copied shared shell with Tickets current, and the shared Preview pill. No `opus-*` files were changed. Original content comes from the supplied assets and `/Users/lume/orch-demo-dash/files-previews/`; no sample figures, spreadsheet sheets, or file bodies were invented.

## Shared decisions and validation

- Bring back the old core's aligned rows, file sizes, and useful type information without raw ticket ids, technical badges, or an activity banner. Grid is comfortable; List provides 40 px rows. Full file names live one click away under File details (BP-04, BP-29, BP-78–82).
- Files are grouped by the nine real steps. The first two groups start open; the remaining groups retain their names, counts, and file summaries. Show all files expands them. This deliberately avoids keeping all 21 thumbnails open by default; at 1920 the grid expands to five columns, at 1280 three. The 12-sample group shows five tiles plus “+7 more”, giving two rows before expansion. List, type, search and expansion persist in the URL.
- All original file bodies remain intact. A first-page PNG was rendered from the real PDF with macOS sips. The missing binary, 25 MB file, long-name text and 12 samples were copied from the original seed, so Download is a real link. The two bulk ZIPs contain those actual files. No network dependency, external font, library, or CDN is used.
- Every page supports `?state=loading`, `?state=empty`, and Loaded / Loading / Empty / Replay in the shared pill. Loading preserves dimensions and hides loaded content from assistive technology; viewer loading uses the fixed stage skeleton. Empty file collections explain how files arrive. An empty viewer means its attachment is no longer available. Error and loading pages default to their named state; `?state=loaded` shows the real PDF in either.
- Validation performed without a browser: JavaScript syntax, HTML duplicate ids, all local src/href/data targets, sandbox presence, expected page count, and source file sizes/content. No timing, contrast rendering, keyboard interaction, PDF browser compatibility, or viewport screenshots are claimed as measured. The manager must verify those in the browser at 1280×800 and 1920×1080. Native PDF controls can capture arrow keys while focused; move focus back to viewer controls to navigate files. Native media and PDF rendering depend on browser support and show an open/download fallback.
- The shell markup is copied from system/shell.html as requested, including its navigation. The source shell's Home count is retained. Review actions are explicitly local demo changes; they do not update the real ticket. Escape returns to the saved collection URL, scroll and focused tile when launched from this area's collection; direct viewer links close to Files. `from=review` returns to the review card. Integrating from another area's ticket requires that page to pass its return context.

## Local components requested for the shared system

`file-group`, `file-grid`, `file-tile`, list mode, the type-filter toolbar, `preview-dialog` lightbox/reading panel, fixed viewer action row, `data-table` with sticky headings, code lines, text search, typed fallback, and review-result layout are defined in previews.css. They use shared color, focus, radius, spacing and motion tokens; no global tokens are overridden. Light document surfaces are file content, not an alternate application theme. A production version should promote these components to the shared preview renderer rather than maintain a separate ticket implementation.

## Common motion contract

First entry: shared page-enter, 150 ms, ease-enter. Only explicit entry/replay animates the page, never background refresh. Viewer entry: 200 ms ease-enter, scale .98→1; reading panel moves 24 px. Close: 150 ms ease-exit, input immediately honored. Tiles/buttons: 100 ms ease-move hover/press. Grid/list/filter/expansion feedback: 120 ms opacity change, no stagger. Native disclosures open instantly. Skeleton-to-content swaps instantly. Reduced motion disables all animation and transitions. No idle ambient motion; the supplied GIF is a static fixture. The product must pause animated media when reduced motion is requested. BP-69–77.

## Common performance contract (targets, not measurements)

Every page: first shell/content ≤100 ms on warm navigation; warm complete <300 ms; cold FCP ≤1.8 s and LCP ≤2.5 s; cold metadata/content target <1 s on a normal desktop connection. INP ≤200 ms, local action target <100 ms. CLS ≤0.1, internal target 0.00 for the reserved viewer stage. Read API p50 <150 ms and p95 <500 ms. Show a shaped skeleton for expected waits ≥1 s, not a flashing spinner for instant local changes. The static mockup does not simulate a real network delay. BP-05, BP-59–67.

The product needs one metadata response (label, original name, MIME type, bytes, dimensions, page count, row count, actor display label, step label, attachment order, downloadable URL), cached thumbnails, safe same-origin media URLs, and a preview endpoint that does not reject a supported extension. Download must bypass preview limits. Prefetch small preview metadata after ≥65 ms hover/focus, skip Save-Data, never prefetch the 25 MB body. Reserve media dimensions, stream/Range large resources, cache results, and update only the affected preview rather than rerender the ticket. Keep file downloads available independently from rendering failures. Raw actor “lume” is retained because it is the actual supplied name; the product needs a display-name mapping before replacing it with a helper/person name.

## files.html — Grouped ticket files

- Show the real 21 files with thumbnails, type, size and time instead of empty preview promises; image URLs are same-origin (PRV-02,03,13,15,16,21).
- Keep step names and counts visible; open a group, filter a type, or switch to the compact list without leaving the ticket (PRV-12,14,20).
- Download all produces a ZIP of the actual 21 files, and every tile opens the matching viewer (PRV-10,14).

**MOTION:** Collection entry 150 ms; hover 100 ms; filter/view/group feedback 120 ms; instant under reduced motion.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Cache the file manifest and first-page thumbnails, batch DOM updates, lazy-load images. Need step ordering, type, bytes and thumbnail dimensions.

## many.html — Twelve files in one step

- Keep all 12 real Sample 01–12 files in natural order under Attach 12 samples at once (PRV-12,14).
- Five visible samples and a +7 more tile explicitly account for all files; expand inline or use the compact list (PRV-02,12).
- Use the actual sample text and a real Download all ZIP, with the same viewer actions as any other file (PRV-10,14,20).

**MOTION:** Entry 150 ms; expansion/view change 120 ms; hover 100 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Fetch the group as one batch; reserve tile heights. Need attachment order and a bulk archive endpoint.

## viewer-pdf.html — PDF

- Embed the real two-page catalogue in a wide native PDF object; open/download remains available if the browser cannot render it (PRV-01,18).
- Show the plain catalogue label, size, step and file position above one consistent action row (PRV-08,10,16).
- Keep loading, unavailable attachment and PDF failure separate; do not collapse the stage during loading (PRV-19,26).

**MOTION:** Lightbox entry 200 ms; close 150 ms; browse entry 200 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Serve application/pdf with Range support and cached first page. Need page count and rendering failure telemetry.

## viewer-html.html — Web page

- Render the actual catalogue HTML in a sandboxed iframe instead of source text (PRV-01,11).
- Give the page 90% of viewport width and a stable action row for opening or downloading the original (PRV-10,18).
- Keep the two-page source content intact; its file size and originating step remain visible (PRV-08,16).

**MOTION:** Lightbox 200 ms; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Serve a separate sandboxed document without dashboard origin privileges. Cache a real page thumbnail; do not load interactive pages in every grid tile.

## viewer-image.html — PNG, JPG, SVG and GIF

- Show the real images in a reserved wide stage, including SVG and GIF (PRV-01,03,23).
- Provide a four-image thumbnail strip, fit/original-size control and keyboard Prev/Next across ticket files (PRV-10,18,20).
- Use the same plain labels and details disclosure; the logo loads as an image, never executable inline markup (PRV-08,16).

**MOTION:** Lightbox 200 ms; hover 100 ms; fit switch instant; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Supply dimensions and sanitized SVG/image URLs; cache thumbnails separately from originals. GIF fixture is static; production needs a still-frame thumbnail and animation preference.

## viewer-table.html — CSV tables

- Render actual rows as columns with sticky headings, row numbers, sorting and preview-row search (PRV-05,21).
- Orders states 5,000 rows and clearly shows only the first 200; search and sorting apply to that preview, with full-file download (PRV-05,09).
- The small Stock CSV uses the same renderer and shows all three real rows (PRV-01,18).

**MOTION:** Lightbox 200 ms; sort/search update instantly; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Stream a bounded row sample and row count, parse CSV in a worker or server, cap raw preview reads at 512 KB. Need verified row/column counts and server-side search for full data.

## viewer-xlsx.html — Spreadsheet

- Render the real Stock sheet as a readable table rather than rejecting the workbook (PRV-01).
- Show the real single sheet as an accessible sheet tab and explicitly say 1 sheet; no fictional sheets (PRV-01,18).
- Include search, sortable columns, row count and original workbook download (PRV-05,10).

**MOTION:** Lightbox 200 ms; search/sort instant; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Parse workbook metadata and bounded cell ranges off the main thread. Need sheet names, dimensions and display-formatted cell values; formulas require safe evaluation or cached results.

## viewer-markdown.html — Rendered note

- Show Spring menu as headings, drinks, prices and the actual image, with Source one click away (PRV-06,21).
- Use a readable side panel rather than raw markup filling a tiny generic sheet (PRV-18).
- Keep content and standard file actions together; the external shop link is rendered as text to keep this mockup offline (PRV-10).

**MOTION:** Panel entry 200 ms; source toggle 120 ms; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Sanitize Markdown HTML, resolve attachment image URLs, and cache parsed output. Need safe link policy and relative attachment mapping.

## viewer-code.html — JSON, Python and JavaScript

- Show actual source with syntax colors, line numbers and a collapsible contents region (PRV-07).
- Copy code operates on visible source lines without numbers; JSON uses readable formatted source in this draft (PRV-07,10).
- Use the plain file label, retaining language and full original name as secondary information (PRV-08,18).

**MOTION:** Panel entry 200 ms; fold instant; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Bound source reads and highlight in a worker. Need language detection; production JSON can add a nested tree if needed, while this draft supports whole-file folding.

## viewer-text.html — Notes, logs, long names and samples

- Render all original text, including the previously failing long-name file; full filename is safely wrapped under File details (PRV-08,24).
- Find in file highlights matches and reports a count, with an explicit wrap toggle for logs (PRV-07).
- Keep notes, log and sample variants in the same reading panel with working download and navigation (PRV-10,18,20).

**MOTION:** Panel entry 200 ms; search/wrap instant; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Stream bounded text and preserve encoding; fix long-name URL handling. Need log level parsing and last-error index for future log-specific controls; this draft searches real log text without inventing an error summary.

## viewer-audio.html — Audio

- Use the real WAV with native playback, seeking, volume and duration rather than a generic failure card (PRV-01).
- Remove the seed-only “no mp3 encoder here” wording; keep Jingle as the label (PRV-22,25).
- Keep the standard actions and prev/next around the player; no autoplay (PRV-10,20).

**MOTION:** Lightbox 200 ms; native player feedback; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Use metadata preload and Range requests; do not fetch all audio before showing the shell. Need duration, content type and an optional real waveform.

## viewer-video.html — Video

- Play the actual 3-second WebM using native controls in a wide reserved stage (PRV-01,18).
- Show a supplied shop photo as the poster while metadata loads; playback is user-initiated (PRV-19,26).
- Keep open, download, copy link and navigation consistent with every other viewer (PRV-10).

**MOTION:** Lightbox 200 ms; native player feedback; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Supply a real video poster, dimensions, duration and supported encodings; use Range and metadata preload. The mockup poster is the provided shop photo, not an extracted frame.

## viewer-zip.html — Archive

- List menu1.txt and menu2.txt with their real uncompressed sizes instead of a blank preview (PRV-01,09).
- State the compressed size and explain that Download opens/extracts the archive (PRV-09,25).
- Use the common viewer shell and actions, with no hidden archive execution (PRV-10,18).

**MOTION:** Lightbox 200 ms; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Read the archive directory server-side with entry-count and size limits. Need entry names, sizes and compressed total; avoid decompressing files merely to list them.

## viewer-unknown.html — Unknown binary

- Explain that .bin cannot be previewed, showing its actual 4 KB size and a direct Download (PRV-09,13,25).
- Keep the plain Unknown binary label; original name is in File details (PRV-08).
- Use a calm fallback card instead of treating an unsupported format as a broken file (PRV-19).

**MOTION:** Lightbox 200 ms; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Inspect metadata only; download must bypass the preview extension allowlist. Need trustworthy bytes, MIME type and download authorization.

## viewer-large.html — 25 MB file

- Say Too large to preview and state both 25 MB size and the proposed 10 MB preview limit (PRV-09,19).
- Download points to the actual supplied 25 MB file; the viewer never embeds or reads its body (PRV-01,09).
- Keep file context and navigation available without a permanent spinner (PRV-10,25).

**MOTION:** Lightbox 200 ms; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. HEAD/manifest size check before loading; never prefetch large bodies. Need per-type limits and reliable size. The 10 MB limit is a proposed product policy, not a measured backend restriction.

## viewer-loading.html — Loading example

- Default to a fixed-size preview skeleton with a plain Loading preview label (PRV-19,26).
- Keep file context, navigation and download available during loading (PRV-10,19).
- Use Loaded in Preview controls to reveal the real PDF, and Empty for an unavailable attachment (PRV-19).

**MOTION:** Viewer entry 200 ms; skeleton static; swap instant; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Resolve metadata before body fetch, abort obsolete requests, reserve stage dimensions. Need loading/error lifecycle separate from attachment existence.

## viewer-error.html — Preview error example

- Default to Couldn’t load the preview, with a working Try again link and independent Download (PRV-09,19,25).
- Keep the file title and context visible so the failed item is unambiguous (PRV-08,16).
- Put the low-level failure explanation under Details; the retry reveals the real PDF (PRV-19,25).

**MOTION:** Viewer entry 200 ms; retry route 200 ms; close 150 ms; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Separate download availability from rendering errors and keep failures beside the preview. Need retriable error categories and a protected original download route.

## review-card.html — Result embedded in review

- Embed the actual final catalogue directly above Accept and Ask for changes, with Expand for a full view (PRV-04).
- Keep Cover photo and Order history as compact supporting previews under the main result (PRV-02,04,21).
- Preserve the missing-task warning and the actual owner/Done when wording; acceptance offers local Undo and changes open an inline form (PRV-04,16).

**MOTION:** Review card first entry 150 ms; verdict feedback 120 ms; hover 100 ms; loading swap instant; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Reuse the file renderer inside review, cache first-page preview and persist verdict optimistically with rollback. Need primary-result ordering, result/support role and approval requirement coverage.

## viewer.html — Viewer index and ticket-link entry

- Provide a useful index of all original files when a ticket link has no file selector (PRV-10,20).
- Resolve file/name/n/type query selectors to the matching dedicated renderer (PRV-01,10).
- Keep the shared shell, state controls and loading/empty handling on this integration page too (PRV-19,26).

**MOTION:** Index entry 150 ms; hover 100 ms; redirect immediately; reduced motion instant.

**Performance:** Common FCP ≤1.8 s, LCP ≤2.5 s, warm fully loaded <300 ms, first shell ≤100 ms, INP ≤200 ms and CLS ≤0.1 targets apply. Resolve stable attachment keys to MIME-aware renderers without a second data waterfall. Product integration needs a stable file key and return URL/scroll/focus contract.

## Integration checks still needed

Browser screenshots and keyboard/assistive-technology verification remain with the manager. Check native PDF rendering under the production CSP, image and media codecs, zoom, focus restore, browser clipboard permissions, reduced motion, row overflow below 900 px, both desktop widths and cold-load metrics. Shared native dialog supplies focus containment. Different document/media frames can consume keyboard shortcuts; visible navigation always remains available. The draft does not claim production latency or full checklist certification from source inspection alone.


## Revised after the owner's comment (13 Nov)

### files.html
- Added Sort beside the type filter: Most important first is the default, followed by Newest first and Oldest first; results come before evidence, then the remaining files. Sorting applies within each task or role group; None gives one sorted list.
- Added By task, By role and None grouping, with choices kept in the page address alongside search and Grid/List.
- Every file now has a role chip, a separate task link and a visible creation date and time in both views. The supplied files all share 13 Nov, 13:38, so date ties retain their original order instead of inventing different times.
- Task links carry the exact task name to ../ticket/ticket-working.html?task=…#ticket-tasks. That separate folder currently has no matching catalogue tasks or task-link handler; its owner must resolve that parameter, select Tasks and open the matching task. No files outside previews were edited.

### many.html
- Added the same Sort and Group choices, keeping the catalogue PDF first as a Result and marking the twelve supplied samples as Evidence for: Attach 12 samples at once.
- Added task links and creation dates to every tile and list row; filtering and grouping recalculate the hidden-file count, and Show all files reveals the remaining samples.
- Preserved all thirteen real files, the sample download, shared shell, Preview pill, loading and empty states, and reduced-motion support.

### viewer-html.html
- The website now loads its own styling, pictures and interactive calculator, so it looks and works like a complete website.
- Added a small responsive Demo Coffee site at assets/site/index.html with separate style.css, script.js and the supplied shop photo; the calculator uses the existing CHF 9.50 beans and CHF 24.00 gift-box prices.
- The full-width preview uses sandbox="allow-scripts" without same-origin access, with Desktop, Tablet and Phone buttons; Open in new tab opens the complete site, and Download website includes all four files in a ZIP.
- The product must serve each site's complete folder at a stable isolated preview URL, preserving relative paths and correct content types for HTML, CSS, JavaScript and images. Its security rules must allow those site resources and scripts without dashboard origin privileges; the new-tab URL must use the same isolated hosting, and downloads must include the whole folder.


Validation for this revision: JavaScript syntax checks passed. Local HTTP browser checks passed for both file counts, sorting/grouping controls, search, list dates, shared Preview pill, loading/empty states, the iframe's CSS and image, the live calculator (two beans plus one gift box = CHF 43.00), and 390 px Phone / 768 px Tablet widths. Serve the mockup over HTTP: opening it as a local file can block external scripts inside an opaque sandbox. Roles are new demonstration metadata; supplied file contents and recorded creation times were preserved. The earlier source-only validation note describes the previous pass.


## Revised after the owner's comment (13 Nov)

Polish pass: this section replaces the earlier advice to open file facts and the warning about local-file website previews. Useful facts are visible without opening anything.

### files.html
- Made each group name a full-width, keyboard-friendly control with a clear chevron and focus outline.
- Kept the real files, visible roles, task links, creation dates, filters and grid/list choices; checked spacing at 1280×800.

### many.html
- Made each group name a full-width, keyboard-friendly control with a clear chevron and focus outline.
- Kept the real files, visible roles, task links, creation dates, filters and grid/list choices; checked spacing at 1280×800.

### review-card.html
- Removed the Details toggle and put the short review explanation beside the actions.
- Checked the result, supporting files and review controls at 1280×800, including loading and empty states.

### viewer-audio.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-code.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-error.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-html.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.
- Embedded the shop styling, calculator and image directly in the preview, so the website works over HTTP and as a local file.
- Kept the styled shop header, illustrated hero, priced product cards and working total calculator; Open in new tab still opens assets/site/index.html.

### viewer-image.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-large.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-loading.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-markdown.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-pdf.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-table.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-text.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-unknown.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-video.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-xlsx.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer-zip.html
- Removed File details and the error Details toggle; type, size, creation time, task and role now appear plainly under the title.
- Kept the action row and footer from shrinking, allowed metadata to wrap, and checked the page at 1280×800 with loading and empty states.

### viewer.html
- Allowed file labels to wrap while keeping their type labels separate.
- Checked all file links and the shared loading and empty layouts at 1280×800.

Validation for this polish pass: visually reviewed all 19 pages at 1280×800 and checked 57 default/loading/empty page states in the browser. No page overflow, clipped checked controls, remaining Details toggles or JavaScript errors were found; each page retains the shared Preview pill. The shop image, styling and CHF 43.00 calculation passed for both local files and HTTP. The current server at 127.0.0.1:8788 serves an older copy outside this assigned folder; HTTP validation therefore used a temporary server on port 18913 serving this mockup root. The 8788 server must serve this edited folder for the requested address to show these revisions. No files outside previews were edited.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### files.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Aligned search, type, sort, group and view choices in one 36 px toolbar row at 1280 px, with labels inside the dropdown buttons.

### many.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Aligned search, type, sort, group and view choices in one 36 px toolbar row at 1280 px, with labels inside the dropdown buttons.

### review-card.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### viewer-audio.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-code.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-error.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-html.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-image.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-large.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-loading.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-markdown.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-pdf.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-table.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-text.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-unknown.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-video.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-xlsx.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer-zip.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### viewer.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.


## Revised after the owner's comment (13 Nov)

QA follow-up: Full screen opens a separate dialog and returns to the same file preview when closed.

### viewer-audio.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-code.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-error.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-html.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-image.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-large.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-loading.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-markdown.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-pdf.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-table.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-text.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-unknown.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-video.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-xlsx.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### viewer-zip.html
- Moved Full screen into the file action row so it is visible and clickable.
- Added a full-screen dialog with Exit full screen, Escape and a clickable backdrop; closing restores the file preview and keyboard focus.
- Kept the real file, loading and empty states, shared Preview pill and reduced-motion behaviour.

### review-card.html
- Expand now opens the catalogue in a dialog on the same page.
- Exit full screen, Escape and a backdrop click return to the review card and restore keyboard focus.
