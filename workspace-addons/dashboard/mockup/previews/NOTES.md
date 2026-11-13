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
