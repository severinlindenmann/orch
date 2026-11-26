## 1. Design flaws and wrong assumptions

- **“Quick look” can become permission to rubber-stamp.** `proposal.verdict == accept`, `one_tap`, and `check_result` do not establish low risk. A helper can choose a reassuring kind or omit risk-bearing details. Unknown risk must not silently become “quick,” and “small and tested” must not appear unless both claims have evidence.

- **The auto-pass claim is misleading.** “Nothing is answered by itself” conflicts with existing Reviewer acceptance. Showing a rule line does not establish which cards it covers, what actually passed, or whether the underlying evidence changed. Keep attention grouping completely separate from authorization; do not change auto-pass eligibility in this work.

- **Authentic words are not necessarily relevant authority.** A genuine quote can concern another option, be conditional, or have been withdrawn. “Newest human message” could be “wait, that’s wrong.” Copying from storage prevents fabricated wording, not misleading attribution. Without an explicit, relevant reference, omit the quote rather than manufacture continuity.

- **The proposed sources cannot all support “You said.”** Another person’s comment is not the current reviewer’s statement; a rules file may be shared, imported, or helper-edited. Require verified authorship and distinguish “You wrote,” “Alex wrote,” and “Team rule.” `rules:<line>` and timestamps are not durable identities: use stable IDs or versioned references, and preserve the source version.

- **Staleness measures activity, not validity.** Six harmless helper edits trigger it; one changed deployment target may not. A card without a quote lacks a baseline. Track the decision’s evidence/artifact version and relevant dependencies. Changed evidence should invalidate a pending approval or require reconfirmation, not merely add a warning.

- **The interaction adds work before proving it saves attention.** Three groups above five lanes, rounds, summaries, menus, context, estimates, and check questions create another review workflow. Hiding tiles at five cards also changes navigation just as the queue shrinks. Start by improving the existing card, not adding a second organization system.

- **The check question risks training another rubber-stamp.** The helper supplies both the question and the “correct” answer; passing it proves neither comprehension nor sound judgment. Hiding the deciding fact until afterward is especially questionable. There is no evidence here that this friction improves decisions.

- **Several fallbacks silently change meaning.** A deadline is not “what happens if you wait”; `--because` is an argument, not necessarily a fact; a short question is not necessarily an actionable decision with clear consequences. Label these honestly, leave absent fields absent, and show what each answer authorizes.

- **The classification and ordering rules conflict.** Project grouping, lane priority, due-date sorting, and attention groups have no defined precedence. Cheap but urgent work could disappear behind a chosen group; critical work can be snoozed. Fixed “about N min” values add false precision, and broad signals such as “words or names” could put nearly everything in “Take your time.”

## 2. Missing pieces

- **Define the execution and answer boundary.** What does accept authorize? Is “Run it” a separate action? Bind decisions to card and artifact versions, reject stale submissions, make retries idempotent, and handle concurrent reviewers. A six-second Undo cannot reverse a command, publication, or downstream action.

- **Specify migration and mixed-version behavior.** Existing cards lack the new fields and may have mutable source records. Define defaults, schema versions, behavior when questions change, preservation of existing answers, and compatibility with older CLI/dashboard/mobile clients. “Additive JSON” does not guarantee old validators or writers behave safely.

- **Treat Later as a persistent state machine, not a hide flag.** Specify time zones, daylight-saving transitions, restart behavior, completed/reopened/deleted dependencies, failed reminders, and visibility across clients. Clarify whether “reminder” means a notification or merely reappearing in the queue. Hidden urgent cards must remain discoverable.

- **Helper compliance needs a measured contract.** Updating `SKILL.md` and printing hints will not reliably produce useful facts. Define which fields are optional, length limits, validation, how helpers learn the interface, and how unsupported claims are handled. Measure field coverage and usefulness rather than filling every slot with a weak fallback.

- **The tests mostly prove rendering, not trustworthiness.** Add fixtures for wrong-author quotes, revoked instructions, changed source versions, missing references, risk-classification false negatives, rule changes, snoozed deadlines, stale answers, and concurrent actions. Include sanitization and permission tests for quotes, links, chat, files, and terminal access.

- **The performance mitigation can break correctness.** Reading only the last 200 history lines may miss the referenced statement or superseding instruction. Define query and latency budgets; batch/index source retrieval, cache by relevant versions, and benchmark large queues. “Shown cards” is undefined when tiles need counts for the whole queue.

- **Phone, accessibility, and alternate surfaces cannot be an unspecified catch-up.** Test keyboard-only operation, screen-reader order, focus restoration, non-swipe actions, narrow screens, zoom, and live updates. Shared widgets do not prove server-page integration works. Either support each surface explicitly or keep the feature disabled there.

- **Add a reversible rollout and a quality measure.** Use a feature switch that restores existing review without losing answers or snoozes; test disable/re-enable and older-client behavior. Baseline and pilot measures should include mistaken approvals found through sampled audits, reversals/rework, missed deadlines, and reviewer burden. Faster acceptance or fewer opened panels alone could mean *more* rubber-stamping.

## 3. Slicing, ordering, and merge-conflict risks

- **The PR strategy contradicts the stated constraint.** The request is to append to 3201 and 3204; the plan primarily waits for them to merge and opens five successors. Choose explicitly: coordinate additions to those open PRs, or obtain approval for a post-merge plan. “Append if still draft” is not a dependency strategy.

- **“One per area” does not mean one giant feature batch.** Slice 1 combines classification, provenance, deadlines, snoozing, quiz fields, and human overrides. Slice 2 combines navigation, card anatomy, and workflow changes. These are too many independently risky behaviors to review together, regardless of the estimated line count.

- **Avoiding `cardkinds.py` does not avoid semantic conflicts.** The new modules still depend on 3201’s unsettled kinds and 3204’s mapping, ordering, and rendering contracts. Agree a minimal producer/consumer contract with both owners first, then put core changes in 3201 and rendering changes in 3204.

- **The side panel unnecessarily expands the dependency graph.** Chat, terminal streams, Focus behavior, overlays, file viewing, and mobile lifecycle add several owners and failure modes unrelated to better decisions. Waiting for their merges avoids some textual conflicts, not integration regressions.

- **Approval and ownership gates are underspecified.** Settle the existing wording contradiction before extending it. Name the owner for each shared file and contract. The reference to “question 3” approving downward moves is also wrong: question 3 concerns “Suggested.” Remove ambiguous approvals before implementation begins.

## 4. Cut further for a useful first version

- **Keep the five lanes and existing navigation.** Cut attention tiles, rounds, summaries, group overrides, and time estimates. Improve the card the person already sees.

- **Show only the decision, the key evidence, and its source.** Use an existing preview or result where appropriate; add one optional short evidence field only if needed. Keep evidence visible. Do not add automatic quotes, activity summaries, stale heuristics, or comprehension gates.

- **Use existing ways to open supporting material.** Cut new chat/terminal tabs, comparison sliders, ideas cards, and persistent reminder workflows. Preserve existing Later and Undo behavior without implying stronger guarantees.

- **Do not make missing fields look complete.** Keep old cards usable, omit unsupported context, and pilot the simpler card behind a switch. Expand only after observing whether people make better decisions—not merely clear cards faster.

## 5. Recommended first pull request — five lines

1. **PR:** Append a minimal card-readability change to **3204**, coordinated with 3201’s owner; no new standalone PR.
2. **Scope:** Put the decision first, followed by existing evidence and its source; preserve lanes, actions, and auto-pass behavior.
3. **Core:** Reuse 3201’s fields; omit missing content rather than inventing quotes, risk labels, or consequences.
4. **Safety:** Use the shared renderer behind a feature switch; test legacy cards, keyboard/phone layouts, and unchanged action semantics.
5. **Gate:** Owner approves the words; pilot against baseline decision-quality and burden measures before adding more workflow.
