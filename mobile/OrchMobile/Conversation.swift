import Foundation

// The phone as a messenger (v3): per workspace one General conversation plus topics (tickets). Pure builders over what the
// relay returned (workspaces, messages, updates, questions) and the Outbox; read state is phone-local. The one rule
// (contracts/relay-api.md "General vs topics"): a workspace text with `ticket` is that topic, otherwise General; a phone text
// with `ticket` is that topic, with `general: true` General, with neither a *new topic* that is "Starting topic…" until a
// workspace ack with `reply_to` = its id names the ticket.

enum ConversationID: Hashable, Sendable {
    case general(workspace: String)
    case topic(workspace: String, ticket: String)
    /// A new topic the workspace has not acked yet. `id` = the text's client_id (stable while it is queued, sent and listed).
    case starting(workspace: String, id: String)

    var workspace: String {
        switch self { case .general(let w), .topic(let w, _), .starting(let w, _): w }
    }
    var ticket: String? { if case .topic(_, let t) = self { t } else { nil } }
    /// Where a message written here goes. A "starting" conversation has no composer target (nothing can be added to it yet).
    var target: SendTarget? {
        switch self {
        case .general(let w): .general(workspace: w)
        case .topic(let w, let t): .topic(workspace: w, ticket: t)
        case .starting: nil
        }
    }
}

enum TopicStatus: String, Sendable, CaseIterable {
    case working, waitingOnYou, review, backlog, done, stopped, didntWork
    /// Short word: group headers and the info summary.
    var label: String {
        switch self {
        case .working: "Working"; case .waitingOnYou: "Needs you"; case .review: "Ready for review"; case .backlog: "Not started"
        case .done: "Done"; case .stopped: "Stopped"; case .didntWork: "Didn't work"
        }
    }
    /// The chip words of the status workflow (PLAN-A section 5).
    var chip: String {
        switch self {
        case .working: "Claude is working"; case .waitingOnYou: "Needs you"; case .review: "Ready for review"; case .backlog: "Not started"
        case .done: "Done"; case .stopped: "Stopped"; case .didntWork: "Didn't work"
        }
    }
    init(_ t: Ticket) {
        switch t.status {
        case .needsYou: self = .waitingOnYou
        case .working: self = .working
        case .review: self = .review
        case .backlog: self = .backlog
        case .done: self = t.view?.status == "dropped" ? .stopped : t.kind == "failure" ? .didntWork : (t.kind == "stopped" ? .stopped : .done)
        }
    }
}

/// Ticks under a message of this phone.
enum Receipt: Equatable, Sendable {
    case queued               // clock: still on the phone
    case sent                 // ✓ the relay stored it
    case delivered            // ✓✓ the workspace has it (delivered_at)
    case started              // ✓✓ + "Started": an ack/working update names it (reply_to)
    case failed(String)       // "Not sent": the relay refused it; Retry / Discard
    var ticks: Int {
        switch self { case .queued, .failed: 0; case .sent: 1; case .delivered, .started: 2 }
    }
}

struct ConvItem: Identifiable, Equatable, Sendable {
    enum Side: Sendable { case me, them }
    enum Kind: Sendable { case message, question }
    let id: String
    /// ISO time; sorts the conversation. Queued items use their creation time.
    let at: String
    let side: Side
    var kind: Kind = .message
    var text: String = ""
    var attachments: [MessageAttachment] = []
    var voice: VoiceMemo? = nil
    var location: LocationShare? = nil
    var feedback: Feedback? = nil
    /// RESULT / DID NOT WORK / STOPPED for update texts.
    var label: String? = nil
    /// Workspace text worth hearing: the speaker button (Speech.swift) uses `id` and `speak.lang`.
    var speak: SpeakHint? = nil
    /// Show the play button: `speak` set and the setting is not `never`, or the setting is `always`.
    var canPlay: Bool = false
    var replyTo: String? = nil
    var receipt: Receipt? = nil
    /// With receipt .started: when the workspace last acked or picked up this text (the General "is working…" line times out from here).
    var workingSince: String? = nil
    /// Phone texts: the client_id (also the id of an outbox item).
    var clientId: String? = nil
    var question: Question? = nil
    /// The answer this phone (or someone else) gave to `question`; nil = open.
    var answer: String? = nil
    /// Files still on the phone (queued uploads): show them from disk.
    var queuedFiles: [PendingFile] = []
    /// What a RESULT update delivered (page, picture, file, pull request): tappable cards in the bubble.
    var artifacts: [TicketSnapshot.Attachment] = []
    var incoming: Bool { side == .them }

    /// One line for lists: the text, else what it carries.
    var preview: String {
        if kind == .question { return question?.message.body.text ?? text }
        if !text.isEmpty { return text }
        if let v = voice, !v.transcript.isEmpty { return v.transcript }
        if voice != nil || attachments.contains(where: { $0.kind == .voice }) { return "Voice message" }
        if let f = (attachments.first ?? nil) { return f.kind == .image ? "Photo" : f.name }
        if !queuedFiles.isEmpty { return queuedFiles[0].kind == .image ? "Photo" : (queuedFiles[0].kind == .voice ? "Voice message" : queuedFiles[0].name) }
        if location != nil { return "Location" }
        if feedback != nil { return "Feedback" }
        return ""
    }
}

struct TopicSummary: Identifiable, Equatable, Sendable {
    let id: ConversationID
    let title: String
    let key: String?
    let status: TopicStatus
    let lastLine: String
    let lastAt: String?
    let unread: Int
    /// "Starting topic…": a new topic the workspace has not acked yet.
    let isStarting: Bool
    let ticket: Ticket?
}

struct ConversationSummary: Equatable, Sendable {
    let id: ConversationID
    let lastLine: String
    let lastAt: String?
    let unread: Int
}

struct WorkspaceSummary: Identifiable, Equatable, Sendable {
    let workspace: Workspace
    let presence: Presence
    let general: ConversationSummary
    let topics: [TopicSummary]
    let openQuestions: Int
    var id: String { workspace.id }
    var unread: Int { general.unread + topics.reduce(0) { $0 + $1.unread } }
    var isMuted: Bool { workspace.isMuted() }
    /// Newest activity in General or any topic.
    var lastAt: String? { ([general.lastAt] + topics.map(\.lastAt)).compactMap { $0 }.max() }
    var lastLine: String { (topics.filter { $0.lastAt != nil && $0.lastAt == lastAt }.first?.lastLine) ?? general.lastLine }
}

struct ConversationInputs: Sendable {
    var workspaces: [Workspace] = []
    var messages: [PhoneMessage] = []
    var tickets: [Ticket] = []
    /// Every question seen, answered or not.
    var questions: [Question] = []
    var answers: [String: String] = [:]
    var outbox: [OutboxItem] = []
    var speak: PhoneSettings.Speak = .auto
    var now: Date = Date()
    /// Phone-local "Delete": chat key -> messages up to this time are hidden (ArchiveStore).
    var erased: [String: String] = [:]
}

extension ReadState {
    func unread(_ chat: String, in items: [ConvItem]) -> Int {
        let s = seen[chat] ?? ""
        return items.filter { $0.incoming && $0.at > s }.count
    }
    static func generalKey(_ ws: String) -> String { "g:" + ws }
    static func key(_ id: ConversationID) -> String {
        switch id {
        case .general(let w): generalKey(w)
        case .topic(let w, let t): ticketKey(w, t)
        case .starting(let w, let c): "s:\(w)|\(c)"
        }
    }
}

enum ConversationBuilder {
    struct Index {
        var ticketOfPhoneText: [String: String] = [:]     // phone text id -> ticket named by an ack
        /// phone text id -> time of its latest ack / working reply ("Working" receipt)
        var startedAt: [String: String] = [:]
        /// "<workspace>|<ticket>" -> time of the latest message that says no agent works on it now: a result, failure or
        /// stopped update, or a snapshot with running false. A "Working" receipt older than that is over (owner 8 Nov, IMG_6624).
        var endedAt: [String: String] = [:]
    }

    private static func isReceipt(_ m: TextMessage) -> Bool {
        guard let k = m.body.update?.kind else { return false }
        return k == "ack" || k == "working"
    }

    static func index(_ d: ConversationInputs) -> Index {
        var ix = Index()
        for pm in d.messages where !pm.fromPhone {
            let m = pm.message
            if let t = m.ticket, ends(m) {
                let k = "\(pm.workspaceId)|\(t)"
                if m.createdAt > (ix.endedAt[k] ?? "") { ix.endedAt[k] = m.createdAt }
            }
            guard isReceipt(m), let r = m.replyTo else { continue }
            if m.createdAt > (ix.startedAt[r] ?? "") { ix.startedAt[r] = m.createdAt }
            if let t = m.ticket, m.body.update?.kind == "ack" { ix.ticketOfPhoneText[r] = t }
        }
        // a question on the ticket: the work waits for the owner ("Needs you"), so the text is no longer "Working"
        for q in d.questions {
            guard let t = q.message.ticket else { continue }
            let k = "\(q.message.from)|\(t)"
            if q.message.createdAt > (ix.endedAt[k] ?? "") { ix.endedAt[k] = q.message.createdAt }
        }
        return ix
    }

    /// A workspace message that says no agent works on its ticket now: a result, failure, stopped or question update, or a
    /// snapshot without a run or waiting for the owner.
    static func ends(_ m: TextMessage) -> Bool {
        if let k = m.body.update?.kind, ["result", "failure", "stopped", "question"].contains(k) { return true }
        return m.body.ticketView?.running == false || m.body.ticketView?.status == "waiting"
    }

    /// The "Working" receipt of this phone text: acked or picked up, and nothing on its ticket said the work stopped since.
    static func isWorking(_ pm: PhoneMessage, _ ix: Index) -> Bool {
        guard let at = ix.startedAt[pm.id] else { return false }
        guard let t = pm.message.ticket ?? ix.ticketOfPhoneText[pm.id], let end = ix.endedAt["\(pm.workspaceId)|\(t)"] else { return true }
        return at > end
    }

    private static func pendingKey(_ pm: PhoneMessage) -> String { pm.clientId ?? pm.message.body.clientId ?? pm.id }

    /// The conversation a stored message belongs to; nil for a receipt (shown as ticks, not as a bubble).
    static func conversation(of pm: PhoneMessage, _ ix: Index? = nil, _ d: ConversationInputs) -> ConversationID? {
        let ix = ix ?? index(d)
        let m = pm.message, ws = pm.workspaceId
        if pm.fromPhone {
            if let t = m.ticket { return .topic(workspace: ws, ticket: t) }
            if m.body.general == true { return .general(workspace: ws) }   // stays in General; the topic it started also shows it first (items)
            if let t = ix.ticketOfPhoneText[pm.id] { return .topic(workspace: ws, ticket: t) }
            return .starting(workspace: ws, id: pendingKey(pm))
        }
        if let k = m.body.update?.kind, !["result", "failure", "stopped"].contains(k) { return nil }   // ack, working, note, question
        if let t = m.ticket { return .topic(workspace: ws, ticket: t) }
        if m.body.general != true, let r = m.replyTo, let t = ix.ticketOfPhoneText[r] { return .topic(workspace: ws, ticket: t) }
        return .general(workspace: ws)
    }

    private static func receipt(_ pm: PhoneMessage, _ ix: Index) -> Receipt {
        if isWorking(pm, ix) { return .started }
        if ix.startedAt[pm.id] != nil { return .delivered }   // picked up, and the work on it has ended since
        return pm.deliveredAt != nil ? .delivered : .sent
    }

    private static func label(_ kind: String?) -> String? { ChatBuilder.label(forKind: kind) }

    private static func bubble(_ pm: PhoneMessage, _ ix: Index, _ d: ConversationInputs) -> ConvItem {
        let m = pm.message, b = m.body
        var item = ConvItem(id: pm.id, at: m.createdAt, side: pm.fromPhone ? .me : .them, text: b.text, attachments: b.attachments, voice: b.voice,
                            location: b.location, feedback: b.feedback)
        item.label = label(b.update?.kind); item.speak = b.speak; item.replyTo = m.replyTo
        if !pm.fromPhone, b.update?.kind == "result" { item.artifacts = b.ticketView?.attachments ?? [] }
        if !pm.fromPhone { item.canPlay = d.speak == .always || (b.speak != nil && d.speak != .never) }
        if pm.fromPhone {
            item.receipt = receipt(pm, ix); item.clientId = pendingKey(pm)
            if item.receipt == .started { item.workingSince = ix.startedAt[pm.id] }
        }
        return item
    }

    private static func queuedBubble(_ o: OutboxItem) -> ConvItem {
        var item = ConvItem(id: "q-" + o.clientId, at: o.createdAt, side: .me, text: o.text ?? "", attachments: [], voice: nil, location: o.location, feedback: nil)
        item.clientId = o.clientId; item.replyTo = o.replyTo
        item.queuedFiles = o.files + (o.voice.map { [$0.file] } ?? [])
        if let v = o.voice { item.voice = VoiceMemo(blobId: v.file.blobId ?? "", transcript: v.transcript, lang: v.lang, langSource: v.langSource) }
        if let f = o.feedback { item.feedback = Feedback(artifactId: f.artifactId, artifactRev: f.artifactRev, verdict: f.verdict) }
        item.receipt = o.failure.map { .failed($0) } ?? (o.sentMessageId != nil ? .sent : .queued)
        return item
    }

    private static func outboxConversation(_ o: OutboxItem) -> ConversationID {
        if let t = o.ticket { return .topic(workspace: o.workspace, ticket: t) }
        return o.general ? .general(workspace: o.workspace) : .starting(workspace: o.workspace, id: o.clientId)
    }

    /// Resolves a "starting" conversation once an ack named its ticket; any other id is returned unchanged.
    static func resolve(_ id: ConversationID, _ d: ConversationInputs) -> ConversationID {
        guard case .starting(let ws, let key) = id else { return id }
        let ix = index(d)
        if let pm = d.messages.first(where: { $0.fromPhone && $0.workspaceId == ws && pendingKey($0) == key }),
           case .topic(let w, let t)? = conversation(of: pm, ix, d) { return .topic(workspace: w, ticket: t) }
        return id
    }

    // MARK: One conversation

    static func items(_ id: ConversationID, _ d: ConversationInputs) -> [ConvItem] {
        let ix = index(d)
        var out: [ConvItem] = []
        var listed = Set<String>()
        for pm in d.messages where pm.workspaceId == id.workspace {
            if let c = pm.clientId ?? pm.message.body.clientId { listed.insert(c) }
            if conversation(of: pm, ix, d) == id { out.append(bubble(pm, ix, d)) }
            else if case .topic(_, let t) = id, pm.fromPhone, pm.message.ticket == nil, ix.ticketOfPhoneText[pm.id] == t { out.append(bubble(pm, ix, d)) }   // General text that started this topic
        }
        for o in d.outbox where o.kind == .send && o.workspace == id.workspace && !listed.contains(o.clientId) && outboxConversation(o) == id {
            out.append(queuedBubble(o))
        }
        for q in d.questions where q.message.from == id.workspace {
            let qid: ConversationID = q.message.ticket.map { .topic(workspace: id.workspace, ticket: $0) } ?? .general(workspace: id.workspace)
            guard qid == id else { continue }
            var item = ConvItem(id: q.id, at: q.message.createdAt, side: .them, kind: .question, text: q.message.body.text)
            item.question = q; item.answer = d.answers[q.id]
            out.append(item)
        }
        out.sort { ($0.at, $0.id) < ($1.at, $1.id) }
        if let cut = d.erased[ReadState.key(id)] { out.removeAll { $0.at <= cut } }
        return out
    }

    // MARK: Lists

    static func topics(workspace ws: String, _ d: ConversationInputs, read: ReadState) -> [TopicSummary] {
        var out: [TopicSummary] = []
        for t in d.tickets where t.workspace == ws && t.ticket != nil {
            let id = ConversationID.topic(workspace: ws, ticket: t.ticket!)
            let its = items(id, d)
            if its.isEmpty, d.erased[ReadState.key(id)] != nil { continue }   // deleted on this phone, nothing new since
            let last = its.last(where: { $0.kind == .message || $0.answer == nil })
            // Activity includes every item and the latest ticket update, independent of the preview selection.
            let lastAt = [its.last?.at, t.at].compactMap { $0 }.max()
            out.append(TopicSummary(id: id, title: t.displayTitle, key: t.key, status: TopicStatus(t), lastLine: last?.preview ?? t.text,
                                    lastAt: lastAt, unread: read.unread(ReadState.key(id), in: its), isStarting: false, ticket: t))
        }
        // New topics that are not acked yet (stored or still queued).
        let ix = index(d)
        var seen = Set<String>()
        for pm in d.messages where pm.fromPhone && pm.workspaceId == ws {
            guard case .starting(_, let key)? = conversation(of: pm, ix, d) else { continue }
            seen.insert(key)
            out.append(startingSummary(.starting(workspace: ws, id: key), text: bubble(pm, ix, d).preview, at: pm.message.createdAt))
        }
        for o in d.outbox where o.kind == .send && o.workspace == ws && o.isNewTopic && !seen.contains(o.clientId) {
            if d.messages.contains(where: { ($0.clientId ?? $0.message.body.clientId) == o.clientId }) { continue }
            out.append(startingSummary(.starting(workspace: ws, id: o.clientId), text: queuedBubble(o).preview, at: o.createdAt))
        }
        return out.sorted { a, b in
            let wa = a.status == .waitingOnYou ? 1 : 0, wb = b.status == .waitingOnYou ? 1 : 0
            return (wa, a.lastAt ?? "") > (wb, b.lastAt ?? "")
        }
    }

    private static func startingSummary(_ id: ConversationID, text: String, at: String) -> TopicSummary {
        TopicSummary(id: id, title: text.isEmpty ? "New topic" : String(text.prefix(60)), key: nil, status: .working, lastLine: "Getting started…", lastAt: at, unread: 0, isStarting: true, ticket: nil)
    }

    static func general(workspace ws: String, _ d: ConversationInputs, read: ReadState) -> ConversationSummary {
        let id = ConversationID.general(workspace: ws), its = items(id, d)
        let last = its.last(where: { $0.kind == .message || $0.answer == nil })
        return ConversationSummary(id: id, lastLine: last?.preview ?? "", lastAt: its.last?.at, unread: read.unread(ReadState.key(id), in: its))
    }

    /// The workspace list: open questions first, then newest activity.
    static func summaries(_ d: ConversationInputs, read: ReadState) -> [WorkspaceSummary] {
        d.workspaces.map { w in
            WorkspaceSummary(workspace: w, presence: w.presence(now: d.now), general: general(workspace: w.id, d, read: read),
                             topics: topics(workspace: w.id, d, read: read),
                             openQuestions: d.questions.filter { $0.message.from == w.id && d.answers[$0.id] == nil }.count)
        }.sorted { ($0.openQuestions > 0 ? 1 : 0, $0.lastAt ?? "") > ($1.openQuestions > 0 ? 1 : 0, $1.lastAt ?? "") }
    }
}

// MARK: Voice language label

enum LanguageLabel {
    /// The language of a conversation: the most used language of its voice memos (ties: the newest), else `fallback` (device language).
    static func conversationLanguage(_ items: [ConvItem], fallback: String = Locale.current.language.languageCode?.identifier ?? "en") -> String {
        var counts: [String: (n: Int, last: Int)] = [:]
        for (i, it) in items.enumerated() { if let l = it.voice?.lang { let c = counts[l] ?? (0, 0); counts[l] = (c.n + 1, i) } }
        return counts.max { ($0.value.n, $0.value.last) < ($1.value.n, $1.value.last) }?.key ?? fallback
    }
    /// "DE-CH" etc. only when the memo's language differs from the conversation's, else nil (no label).
    static func label(memo: String, conversation: String) -> String? {
        memo.caseInsensitiveCompare(conversation) == .orderedSame ? nil : memo.uppercased()
    }
}
