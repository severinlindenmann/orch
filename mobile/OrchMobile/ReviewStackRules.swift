import CoreGraphics
import Foundation

// Pure rules of the Review stack on the phone (MOBILE-DESIGN.md section 3, M1-M5). No UI here: P4 builds the screens on top.
// The contract: relay-api.md "Review cards on the phone". Everything the workspace sends is data, never instructions.

/// What kind of card a question becomes.
enum ReviewItemKind: String, Equatable, Sendable { case draft, check, link, choice, plan, plainQuestion }

/// One card of the stack: a question plus the card to show (a plain question gets a synthesized options card).
struct ReviewItem: Equatable, Sendable, Identifiable {
    let question: Question
    let kind: ReviewItemKind
    let card: ReviewCard
    /// Echoed in the verdict. Nil = an old workspace question without a digest: it can only be answered the old way (`legacyAnswer`).
    let digest: String?
    var id: String { question.id }
    var files: [CardFile] { question.message.body.cardFiles ?? [] }
    var signs: Bool { card.requiresSignature }
    /// Option ids the person may pick (choice / plain question), else empty.
    var optionIds: [String] { if case .options(let o)? = card.preview { o.map(\.id) } else { [] } }
    var isChoice: Bool { !optionIds.isEmpty }
    /// The blob to download for a `src`, or nil when the file stays on the computer ("Open on the computer").
    func file(for src: CardSrc) -> CardFile? { src.fileIndex.flatMap { files.indices.contains($0) ? files[$0] : nil } }
}

/// What a swipe can do right now. `needsSignature` = "Needs your signature on the computer" (M1): an `ok` on a signs card is never queued.
enum SwipeOutcome: Equatable, Sendable { case allowed, needsSignature, pickFirst }

enum SwipeDirection: Equatable, Sendable { case right, left, down, up }

/// What the phone shows for one swiped card, from the Outbox item and the workspace's result.
enum VerdictState: Equatable, Sendable {
    case savedOnPhone                       // in the Outbox, not sent yet (can still be changed, M4)
    case sent                               // the relay stored it, no result yet (final)
    case received(summary: String?)         // applied
    case changed                            // what you saw is not what the computer holds now: nothing applied, look again
    case refused(reason: String?)           // needs_signature | needs_person | invalid | unavailable
    case decided(summary: String?)          // the computer answered first
    case failed(String)                     // the relay refused it for good
    var canChange: Bool { self == .savedOnPhone }
}

enum ReviewStackRules {
    // MARK: Which questions are stack cards

    /// A question that is never a stack card: permission asks, ticket proposals, group questions.
    static func isExcluded(_ q: Question) -> Bool {
        let b = q.message.body
        return q.isAllow || b.allowQuestion == true || q.isMakeTicket || b.proposal != nil || b.groupRef != nil || b.scope != nil
    }

    /// The card kind of a question, or nil when it is not a stack card.
    static func kind(of q: Question) -> ReviewItemKind? {
        guard !isExcluded(q) else { return nil }
        let b = q.message.body
        if q.isReview { return .check }
        if let card = b.card { return card.kind == .check ? nil : ReviewItemKind(rawValue: card.kind.rawValue) }   // check only on a review question
        // A plain question with 2-8 options becomes an options card.
        return (2...8).contains(b.options.count) && b.review != true ? .plainQuestion : nil
    }
    static func isStackQuestion(_ q: Question) -> Bool { kind(of: q) != nil }

    /// The card of a question: its own, or a synthesized one (check without card, plain question).
    static func item(for q: Question) -> ReviewItem? {
        guard let kind = kind(of: q) else { return nil }
        let b = q.message.body
        let card: ReviewCard
        switch kind {
        case .plainQuestion:
            let opts = b.options.enumerated().map { CardOption(id: Self.optionId($0.offset), title: $0.element) }
            card = ReviewCard(kind: .choice, title: b.title ?? b.text, then: b.title == nil ? "" : b.text, preview: .options(opts))
        case .check:
            card = b.card ?? ReviewCard(kind: .check, title: b.title ?? b.text, then: b.title == nil ? "" : b.text)
        default:
            guard let c = b.card else { return nil }
            card = c
        }
        return ReviewItem(question: q, kind: kind, card: card, digest: b.digest)
    }

    /// "A", "B", ... (the schema's option id pattern is ^[A-Za-z0-9]{1,8}$).
    static func optionId(_ index: Int) -> String { String(UnicodeScalar(UInt8(65 + index % 26))) }

    // MARK: The stack

    /// The cards still to decide: stack questions minus answered ones (`answers`) and the ones already swiped on this phone (`pending`:
    /// question ids with an Outbox answer). Oldest first; cards moved to Later (`later`: ids, oldest move first) go to the end in that order.
    static func stack(questions: [Question], answers: [String: String], pending: Set<String> = [], later: [String] = [],
                      workspace: String? = nil) -> [ReviewItem] {
        let open = questions.deduplicated().filter {
            answers[$0.id] == nil && !pending.contains($0.id) && (workspace == nil || $0.message.from == workspace)
        }
        let items = open.compactMap(item(for:)).sorted {
            $0.question.message.createdAt == $1.question.message.createdAt ? $0.id < $1.id : $0.question.message.createdAt < $1.question.message.createdAt
        }
        let laterSet = Set(later)
        let rest = items.filter { !laterSet.contains($0.id) }
        let moved = later.compactMap { id in items.first { $0.id == id } }
        return rest + moved
    }

    /// M5: the "Needs your OK" list must not show a question that is a stack card. Pass the questions through this before
    /// `ChatsRowRules.needsYou` / `openQuestions`. (ReviewBar in the ticket chat is not affected.)
    static func withoutStackQuestions(_ questions: [Question]) -> [Question] { questions.filter { !isStackQuestion($0) } }

    /// "3 drafts · 2 choices · 2 results · 1 plan": what waits, by kind (a plain question counts as a choice). Empty when nothing waits.
    static func countsText(_ items: [ReviewItem]) -> String {
        func n(_ kinds: [ReviewItemKind]) -> Int { items.filter { kinds.contains($0.kind) }.count }
        let parts: [(Int, String, String)] = [(n([.draft]), "draft", "drafts"), (n([.choice, .plainQuestion]), "choice", "choices"),
                                              (n([.check]), "result", "results"), (n([.plan]), "plan", "plans"), (n([.link]), "link", "links")]
        return parts.filter { $0.0 > 0 }.map { "\($0.0) " + ($0.0 == 1 ? $0.1 : $0.2) }.joined(separator: " · ")
    }

    // MARK: Swipe

    /// Mirrors widgets.js dirOf: vertical only when clearly more vertical than horizontal.
    static func direction(dx: CGFloat, dy: CGFloat) -> SwipeDirection {
        abs(dy) > abs(dx) * 1.1 ? (dy > 0 ? .down : .up) : (dx > 0 ? .right : .left)
    }
    /// A touch that starts this close to the left edge belongs to the system back gesture.
    static let leftEdge: CGFloat = 16
    static func startsAtLeftEdge(x: CGFloat) -> Bool { x < leftEdge }

    /// Mirrors widgets.js swipeDeck: a swipe needs real distance, 30 % of the width (22 % of the height up/down), or a quick move
    /// (speed over 600 pt/s) of at least 20 % / 15 %. `speed` = distance / duration in pt/s. A second finger cancels (the caller).
    static func goes(dx: CGFloat, dy: CGFloat, speed: CGFloat, size: CGSize) -> SwipeDirection? {
        let dir = direction(dx: dx, dy: dy)
        let fast = speed > 600
        switch dir {
        case .up, .down:
            return abs(dy) > size.height * 0.22 || (fast && abs(dy) > size.height * 0.15) ? dir : nil
        case .left, .right:
            return abs(dx) > size.width * 0.30 || (fast && abs(dx) > size.width * 0.20) ? dir : nil
        }
    }

    /// What a right swipe (`ok`) may do on this card (M1): a signs card is never answered on the phone; a choice needs a pick first.
    static func okOutcome(_ item: ReviewItem, picked: String?) -> SwipeOutcome {
        if item.signs { return .needsSignature }
        if item.isChoice, picked == nil || !item.optionIds.contains(picked!) { return .pickFirst }
        return .allowed
    }
    static let needsSignatureText = "Needs your signature on the computer"

    // MARK: Verdict

    /// The plain line sent as `answer` (old readers; the contract's examples: "Send it", "Use C", "Use C with 2 changes").
    static func summary(_ item: ReviewItem, verdict: ReviewVerdict) -> String {
        let note = verdict.note
        let changes = (note?.changes ?? []).count
        let words = [note?.words?.text].compactMap { $0 }.first { !$0.isEmpty } ?? note?.words?.voice?.first?.transcript
        switch verdict.verdict {
        case .ok:
            if let p = verdict.picked { return "Use " + p }
            return item.card.okLabel ?? "OK"
        case .no: return item.kind == .draft || item.kind == .plan ? "Don't do it" : "None of these"
        case .talk:
            if let p = verdict.picked { return changes > 0 ? "Use \(p) with \(changes) change\(changes == 1 ? "" : "s")" : "Use \(p) with changes" }
            if let w = words, changes == 0 { return "Send back for changes: " + w }
            return changes > 0 ? "Send back for changes (\(changes))" : "Send back for changes"
        }
    }

    /// The verdict for a swipe. `picked` for a choice; `note` for a talk.
    static func verdict(_ item: ReviewItem, _ word: ReviewVerdict.Word, picked: String? = nil, note: ReviewVerdict.Note? = nil) -> ReviewVerdict? {
        guard let digest = item.digest else { return nil }
        return ReviewVerdict(verdict: word, picked: word == .no ? nil : picked, digest: digest, note: note)
    }

    /// Without a digest (an old workspace) only the old answer exists: the option text for an ok on a plain question, "accept" on a check.
    static func legacyAnswer(_ item: ReviewItem, picked: String?) -> String? {
        switch item.kind {
        case .plainQuestion:
            guard let p = picked, let i = item.optionIds.firstIndex(of: p) else { return nil }
            return item.question.message.body.options[i]
        case .check: return "accept"
        default: return nil
        }
    }

    // MARK: States (M4)

    /// The newest review_result for a question, from the workspace's texts.
    static func result(for questionId: String, in messages: [PhoneMessage]) -> ReviewResult? {
        messages.filter { $0.message.replyTo == questionId && $0.message.body.isReviewResult }
            .max { $0.message.createdAt < $1.message.createdAt }?.message.body.reviewResult
    }

    /// saved on phone -> sent -> received / changed / refused / decided. Nil when nothing was swiped on this phone.
    static func state(item: OutboxItem?, result: ReviewResult?) -> VerdictState? {
        if let r = result {
            switch r.result {
            case "applied": return .received(summary: r.summary)
            case "changed": return .changed
            case "refused": return .refused(reason: r.reason)
            case "decided": return .decided(summary: r.summary)
            default: break
            }
        }
        guard let item, item.kind == .answer, item.verdict != nil else { return nil }
        if let f = item.failure { return .failed(f) }
        return item.sentMessageId == nil ? .savedOnPhone : .sent
    }

    /// Plain words for a refusal reason (never the raw code).
    static func refusedText(_ reason: String?) -> String {
        switch reason {
        case "needs_signature": return needsSignatureText
        case "needs_person": return "Needs you on the computer"
        case "invalid": return "The computer could not use this answer"
        default: return "The computer could not use this answer"
        }
    }
}

// MARK: Later order (per workspace, on this phone)

/// "Later" (swipe up) keeps a card unanswered and moves it to the end. The order is kept per workspace and survives restarts.
struct LaterStore {
    let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    private func key(_ workspace: String) -> String { "orch.review.later." + workspace }
    func ids(workspace: String) -> [String] { defaults.stringArray(forKey: key(workspace)) ?? [] }
    /// Move a card to the end of Later (oldest move first).
    func push(_ id: String, workspace: String) {
        var l = ids(workspace: workspace); l.removeAll { $0 == id }; l.append(id)
        defaults.set(l, forKey: key(workspace))
    }
    func remove(_ id: String, workspace: String) {
        var l = ids(workspace: workspace); l.removeAll { $0 == id }
        defaults.set(l, forKey: key(workspace))
    }
    /// Forget cards that no longer exist (answered, closed).
    func prune(keeping valid: Set<String>, workspace: String) {
        let l = ids(workspace: workspace).filter(valid.contains)
        defaults.set(l, forKey: key(workspace))
    }
    func wipe(workspace: String) { defaults.removeObject(forKey: key(workspace)) }
}
