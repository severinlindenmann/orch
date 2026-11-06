import Foundation

/// The phone as a messenger: pure builders for the chats list, the workspace chat and the ticket chat.
/// Built from what the relay already returns (workspaces, messages, updates, questions); read state and search live on the phone only.

enum ChatRoute: Hashable {
    case workspace(String)
    case ticket(workspace: String, ticket: String)
    case newChat
    case newTopic(String)
    case info(workspace: String, ticket: String?)
}

struct QueuedText: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let workspace: String
    let ticket: String?
    let text: String
    let at: String
    /// The phone id (credential) this text was written under; a different phone never sends it.
    var phone: String = ""
}

struct ChatItem: Identifiable, Equatable {
    enum Kind: Equatable {
        case mine(String, queued: Bool)
        case theirs(String, label: String?, sender: String? = nil)     // label: "RESULT" etc.; sender: "Claude · agent"
        case system(String)
        case card(Ticket)
        case question(Question)
        case attachment(TicketSnapshot.Attachment)
    }
    let id: String
    let at: String
    let kind: Kind
    var incoming: Bool {
        switch kind {
        case .theirs, .question, .attachment, .card: return true
        case .mine, .system: return false
        }
    }
}

struct TicketRow: Identifiable, Equatable {
    let ticket: Ticket
    let unread: Int
    var id: String { ticket.id }
}

struct RoomRow: Identifiable, Equatable {
    let workspace: Workspace
    let lastLine: String
    let lastAt: String?
    let unread: Int
    let openQuestions: Int
    let tickets: [TicketRow]
    var id: String { workspace.id }
}

/// Which message the last visit has seen, per chat. Client only.
struct ReadState: Equatable {
    private(set) var seen: [String: String] = [:]
    static func workspaceKey(_ ws: String) -> String { "ws:" + ws }
    static func ticketKey(_ ws: String, _ t: String) -> String { "t:\(ws)|\(t)" }
    mutating func markRead(_ chat: String, upTo at: String) { if (seen[chat] ?? "") < at { seen[chat] = at } }
    func unread(_ chat: String, in items: [ChatItem]) -> Int {
        let s = seen[chat] ?? ""
        return items.filter { $0.incoming && $0.at > s }.count
    }
    init(seen: [String: String] = [:]) { self.seen = seen }
}

enum ChatFilter: String, CaseIterable, Identifiable {
    case all = "All", needsYou = "Needs you", workspaces = "Workspaces", tickets = "Tickets"
    var id: String { rawValue }
}

struct SearchHit: Identifiable, Equatable {
    let id: String
    let route: ChatRoute
    let who: String
    let text: String
    let at: String
}

struct ChatSearchResult: Equatable {
    var chats: [TicketRow] = []
    var rooms: [RoomRow] = []
    var messages: [SearchHit] = []
    var isEmpty: Bool { chats.isEmpty && rooms.isEmpty && messages.isEmpty }
}

struct ChatData {
    var workspaces: [Workspace] = []
    var messages: [PhoneMessage] = []
    var tickets: [Ticket] = []
    var questions: [Question] = []      // every question seen, answered or not
    var answers: [String: String] = [:]
    var outbox: [QueuedText] = []

    func isOpen(_ q: Question) -> Bool { answers[q.id] == nil }
}

enum ChatBuilder {
    /// Plain-word label of an update kind, nil for ordinary ones.
    static func label(forKind kind: String?) -> String? {
        switch kind { case "result": "RESULT"; case "failure": "DID NOT WORK"; case "stopped": "STOPPED"; default: nil }
    }

    private static func isMine(_ line: TicketSnapshot.Line) -> Bool {
        ["person", "you", "human", "me"].contains((line.role ?? line.by ?? "").lowercased())
    }

    // MARK: Workspace chat

    static func workspaceItems(_ ws: String, _ d: ChatData) -> [ChatItem] {
        var out: [ChatItem] = []
        let keyOf = Dictionary(d.tickets.filter { $0.workspace == ws }.compactMap { t in t.ticket.map { ($0, t) } }, uniquingKeysWith: { a, _ in a })
        for m in d.messages where m.workspaceId == ws {
            let msg = m.message
            if let u = msg.body.update {
                guard u.kind == "ack" else { continue }          // the rest lives on the ticket card and in the ticket chat
                let key = msg.key ?? msg.ticket.flatMap { keyOf[$0]?.key }
                let title = u.title ?? msg.body.text
                out.append(ChatItem(id: "sys-" + m.id, at: msg.createdAt,
                                    kind: .system("Ticket created: " + [key, title].compactMap { $0 }.joined(separator: " · "))))
                out.append(ChatItem(id: m.id, at: msg.createdAt + "~", kind: .theirs(msg.body.text, label: nil)))
            } else if msg.ticket == nil {
                out.append(ChatItem(id: m.id, at: msg.createdAt, kind: m.fromPhone ? .mine(msg.body.text, queued: false) : .theirs(msg.body.text, label: nil)))
            }
        }
        for t in d.tickets where t.workspace == ws && t.ticket != nil { out.append(ChatItem(id: "card-" + t.id, at: t.at + "~", kind: .card(t))) }
        for q in d.questions where q.message.from == ws { out.append(ChatItem(id: q.id, at: q.message.createdAt, kind: .question(q))) }
        for q in d.outbox where q.workspace == ws && q.ticket == nil { out.append(ChatItem(id: "q-" + q.id, at: q.at, kind: .mine(q.text, queued: true))) }
        return out.sorted { ($0.at, $0.id) < ($1.at, $1.id) }
    }

    // MARK: Ticket chat

    static func ticketItems(_ ws: String, _ ticketId: String, _ d: ChatData) -> [ChatItem] {
        var out: [ChatItem] = []
        let t = d.tickets.first { $0.workspace == ws && $0.ticket == ticketId }
        var seenText = Set<String>()
        for m in d.messages where m.workspaceId == ws && m.message.ticket == ticketId {
            let msg = m.message
            seenText.insert(msg.body.text)
            if m.fromPhone { out.append(ChatItem(id: m.id, at: msg.createdAt, kind: .mine(msg.body.text, queued: false))); continue }
            if msg.body.update?.kind == "ack" || msg.body.update?.kind == "note" { continue }
            out.append(ChatItem(id: m.id, at: msg.createdAt, kind: .theirs(msg.body.text, label: label(forKind: msg.body.update?.kind))))
        }
        // History from the snapshot (last 30), without repeating a line an update text already shows.
        for (i, line) in (t?.view?.historyTail ?? []).suffix(30).enumerated() where !seenText.contains(line.text) {
            let at = line.at ?? "0000"
            out.append(ChatItem(id: "h\(i)-" + line.id, at: at, kind: isMine(line) ? .mine(line.text, queued: false) : .theirs(line.text, label: nil, sender: line.by.map { "\($0) · \(line.role ?? "agent")" })))
        }
        for a in t?.view?.attachments ?? [] { out.append(ChatItem(id: "a-" + a.id, at: (a.at ?? t?.at ?? "0000") + "~", kind: .attachment(a))) }
        for q in d.questions where q.message.from == ws && q.message.ticket == ticketId { out.append(ChatItem(id: q.id, at: q.message.createdAt, kind: .question(q))) }
        for q in d.outbox where q.workspace == ws && q.ticket == ticketId { out.append(ChatItem(id: "q-" + q.id, at: q.at, kind: .mine(q.text, queued: true))) }
        return out.sorted { ($0.at, $0.id) < ($1.at, $1.id) }
    }

    // MARK: Chats list

    static func rooms(_ d: ChatData, read: ReadState) -> [RoomRow] {
        d.workspaces.map { w in
            let items = workspaceItems(w.id, d)
            let open = d.questions.filter { $0.message.from == w.id && d.isOpen($0) }
            let tickets = d.tickets.filter { $0.workspace == w.id && $0.ticket != nil }.map { t -> TicketRow in
                let tItems = ticketItems(w.id, t.ticket!, d)
                return TicketRow(ticket: t, unread: read.unread(ReadState.ticketKey(w.id, t.ticket!), in: tItems))
            }
            let line: String, at: String?
            if let q = open.last { line = q.message.body.text; at = q.message.createdAt }
            else if let last = items.last(where: { if case .theirs = $0.kind { return true }; if case .mine = $0.kind { return true }; return false }) {
                switch last.kind { case .theirs(let t, _, _): line = t; case .mine(let t, _): line = t; default: line = "" }
                at = last.at
            } else { line = lastSeenText(w.lastSeen, online: w.online); at = nil }
            let unread = read.unread(ReadState.workspaceKey(w.id), in: items)
            return RoomRow(workspace: w, lastLine: line, lastAt: at.map { String($0.prefix(while: { $0 != "~" })) }, unread: unread, openQuestions: open.count, tickets: tickets)
        }.sorted { ($0.openQuestions > 0 ? 1 : 0, $0.lastAt ?? "") > ($1.openQuestions > 0 ? 1 : 0, $1.lastAt ?? "") }
    }

    static func filtered(_ rows: [RoomRow], _ f: ChatFilter) -> [RoomRow] {
        switch f {
        case .all, .workspaces: return rows
        case .needsYou: return rows.compactMap { r in
            let t = r.tickets.filter { $0.ticket.status == .needsYou }
            return r.openQuestions > 0 || !t.isEmpty ? RoomRow(workspace: r.workspace, lastLine: r.lastLine, lastAt: r.lastAt, unread: r.unread, openQuestions: r.openQuestions, tickets: t) : nil
        }
        case .tickets: return rows.filter { !$0.tickets.isEmpty }
        }
    }

    // MARK: Search (client only, over what is loaded)

    static func search(_ query: String, _ d: ChatData, rows: [RoomRow]) -> ChatSearchResult {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return ChatSearchResult() }
        var r = ChatSearchResult()
        r.rooms = rows.filter { $0.workspace.displayName.lowercased().contains(q) }
        r.chats = rows.flatMap(\.tickets).filter {
            ($0.ticket.key ?? "").lowercased().contains(q) || $0.ticket.displayTitle.lowercased().contains(q) || ($0.ticket.ticket ?? "").lowercased() == q
        }
        for m in d.messages where m.message.body.update == nil || m.message.body.update?.kind == "result" {
            guard m.message.body.text.lowercased().contains(q) else { continue }
            let who = (m.fromPhone ? "You" : m.workspaceName)
            let route: ChatRoute = m.message.ticket.map { .ticket(workspace: m.workspaceId, ticket: $0) } ?? .workspace(m.workspaceId)
            r.messages.append(SearchHit(id: m.id, route: route, who: who, text: m.message.body.text, at: m.message.createdAt))
        }
        r.messages.sort { $0.at > $1.at }
        return r
    }

    // MARK: Composer wording

    static func composerNote(running: Bool?) -> String {
        running == true ? "Goes in after this step" : "Saved for the next run"
    }

    /// Display time: "9:41" today, otherwise a short date.
    static func timeText(_ iso: String, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard let d = ISO8601DateFormatter().date(from: String(iso.prefix(while: { $0 != "~" }))) else { return "" }
        let f = DateFormatter()
        if calendar.isDate(d, inSameDayAs: now) { f.dateFormat = "H:mm" }
        else if calendar.isDate(d, inSameDayAs: calendar.date(byAdding: .day, value: -1, to: now) ?? now) { return "Yesterday" }
        else { f.dateFormat = "d MMM" }
        return f.string(from: d)
    }
}
