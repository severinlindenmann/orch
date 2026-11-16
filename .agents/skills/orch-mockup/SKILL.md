---
name: orch-mockup
description: Use for ANY orch UI, visual, screen, page, flow, dialog, wording-on-screen, empty/error state, mockup, draft or "how does it look" work - building or changing a dashboard/add-on/relay/publish/mobile screen, a UX item, a visual draft, QA visual verification, or adding mock data. The mockup is the visual source of truth (AGENTS.md R6.3); this says where it lives, how to open it and how to compare product vs mockup vs draft.
---

# orch mockup: the visual source of truth

## First: the one design system
Read skill `orch-design-system`. The mockup links the master library (`workspace/src/orch_ui/static/`) by relative
path; never add a page-local look or a copied kit. Every UI change also runs skill `orch-ux-checklist` (UX/UI
checklist, screenshots at 1280, 1920 and 390, result in the PR body).

## Where
`workspace-addons/dashboard/mockup/<area>/*.html` (areas: home, board, ticket, chat, review, settings, relay,
publish, automation, factory, focus, insights, lessons, notes, sync, errors, previews, proposals, system, sweep).
Static pages: serve them from a static server rooted at the repo so the relative links to the master resolve, e.g.
`python3 -m http.server <port> --bind 127.0.0.1 --directory <repo>` and open `/workspace-addons/dashboard/mockup/<area>/`.
Owner-visible links: port 8780-8799 on 127.0.0.1, link as the user skill share-with-severin says; check with curl for
200 first.

## The rule
- Every UI change updates the matching mockup in the SAME PR (PR template line "master library + gallery + mockup").
- A mockup never shows UI the product doesn't have; the product never ships a screen or state the mockup lacks.
- Only exception: Preview add-ons, always with a visible "Preview" tag; the PR that ships the add-on removes the tag.

## Compare product, mockup, draft
- Shots at 1280, 1920 and 390 px of each (`~/orch-dev/scripts/shot.sh <url> <file>.png <width>` or your own Chromium
  with a temp profile). Attach them to the ticket as evidence (`orch check done ... --file`), not into git.
- Checklist: same title, nav label, button words, block order, tokens/spacing; empty, loading, error and offline states;
  no VPN product name; no typed confirm words; nothing in the mockup the product lacks. The full UX/UI checklist is
  skill `orch-ux-checklist`.

## Owner design rules (every screen)
- Minimal plain words for non-technical users; minimum info, detail lower down.
- Every admin action is a plain click in the dashboard; the CLI is only the backup.
- Visual changes: local HTML draft first (variants), one challenge (a second helper or the API credit), recommended
  pick, then build.
- The workspace works fully without any server (relay/publish/hub are optional).
