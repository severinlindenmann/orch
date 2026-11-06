import Foundation

/// Wire models of the phone API (contracts/relay-api.md). Unknown fields are ignored.
struct ListResponse<T: Decodable & Sendable>: Decodable, Sendable {
    let items: [T]
    let next: String?
}

struct WorkspaceRef: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let name: String
    var displayName: String { OrchMobile.displayName(name) }
}

struct PairResponse: Decodable, Sendable {
    let phoneId: String
    let token: String
    let workspaces: [WorkspaceRef]
}

/// Workspace names are shown exactly as the relay returns them.
func displayName(_ raw: String) -> String { raw.trimmingCharacters(in: .whitespacesAndNewlines) }

struct Workspace: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let name: String
    let description: String?
    let tags: [String]
    let online: Bool
    let lastSeen: String?
    let openQuestions: Int
    var displayName: String { OrchMobile.displayName(name) }
}

struct QuestionBody: Codable, Sendable, Equatable {
    let questionId: String
    let title: String?
    let text: String
    let options: [String]
    let recommended: String?
}

struct QuestionMessage: Codable, Sendable, Equatable {
    let schema: String
    let id: String
    let from: String
    let to: String
    let type: String
    let createdAt: String
    let ticket: String?
    let body: QuestionBody
    /// Display key like PIL-12 (optional: older workspaces do not send it).
    var key: String? = nil
}

struct Question: Codable, Sendable, Equatable, Identifiable {
    let message: QuestionMessage
    let workspaceName: String
    var id: String { message.id }
    /// A `relay:allow` question: a workspace handed over a task that is not allowed yet (SA-12). Answered like any question.
    var isAllow: Bool { message.body.options.contains("Once") && message.body.options.contains("Always") }
    /// Button wording; the raw option is what gets sent.
    func label(_ option: String) -> String {
        guard isAllow else { return option }
        switch option { case "Once": return "Allow once"; case "Always": return "Always"; case "No": return "Ignore"; default: return option }
    }
    var workspaceDisplayName: String { displayName(workspaceName) }
    /// Same ticket, same asker, same wording = the same question, even if the relay delivered it more than once.
    var contentKey: String { [message.from, message.ticket ?? "", message.body.questionId, message.body.text].joined(separator: "\u{1f}") }
}

extension Array where Element == Question {
    /// One card per message id and per identical question (newest message wins).
    func deduplicated() -> [Question] {
        var seenIDs = Set<String>(), seenContent = Set<String>(), out: [Question] = []
        for q in sorted(by: { $0.message.createdAt > $1.message.createdAt }) {
            guard seenIDs.insert(q.id).inserted, seenContent.insert(q.contentKey).inserted else { continue }
            out.append(q)
        }
        return out.sorted { $0.message.createdAt < $1.message.createdAt }
    }
}

/// `GET /v1/phone/messages`: a text between this phone and a workspace (either direction).
struct TextBody: Codable, Sendable, Equatable {
    let text: String
    /// Work update about the message's ticket (contracts/message.schema.json); nil on a plain text.
    var update: TextUpdate? = nil
}
struct TextUpdate: Codable, Sendable, Equatable { let kind: String; var title: String? = nil }
struct TextMessage: Codable, Sendable, Equatable {
    let id: String
    let from: String
    let to: String
    let type: String
    let createdAt: String
    let ticket: String?
    let body: TextBody
    var key: String? = nil
}
struct PhoneMessage: Codable, Sendable, Equatable, Identifiable {
    let message: TextMessage
    let workspaceName: String
    var id: String { message.id }
    var fromPhone: Bool { message.from.hasPrefix("ph_") }
    /// The workspace on the other side of the conversation.
    var workspaceId: String { fromPhone ? message.to : message.from }
}

/// `GET /v1/phone/updates`: one item per (workspace, ticket), its newest update first.
struct TicketUpdate: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let workspace: String
    let workspaceName: String
    let ticket: String
    let kind: String
    let title: String?
    let text: String
    let replyTo: String?
    let at: String
    var key: String? = nil
    /// Snapshot of the ticket (tasks, history, proof). Optional: absent until the workspace sends it.
    var ticketView: TicketSnapshot? = nil
}

/// `body.ticket_view` of a work update (docs TECH-NOTES "What is new"). Every field is optional so the app works before and after it ships.
struct TicketSnapshot: Codable, Sendable, Equatable {
    struct Task: Codable, Sendable, Equatable {
        let text: String; var done: Bool
        init(text: String, done: Bool = false) { self.text = text; self.done = done }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            text = try c.decode(String.self, forKey: .text); done = (try? c.decodeIfPresent(Bool.self, forKey: .done)) ?? false
        }
        enum CodingKeys: String, CodingKey { case text, done }
    }
    struct Attachment: Codable, Sendable, Equatable, Identifiable {
        var kind: String = "file"      // image | link | file
        var title: String? = nil
        var url: String? = nil
        var blobId: String? = nil
        var name: String? = nil
        var size: Int? = nil
        var at: String? = nil
        var id: String { [kind, blobId ?? url ?? name ?? title ?? "", at ?? ""].joined(separator: "|") }
        /// What a person reads: the proof title, else the file name.
        var label: String? { title ?? name }
        init(kind: String = "file", title: String? = nil, url: String? = nil, blobId: String? = nil, name: String? = nil, size: Int? = nil, at: String? = nil) {
            self.kind = kind; self.title = title; self.url = url; self.blobId = blobId; self.name = name; self.size = size; self.at = at
        }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "file"
            title = try? c.decodeIfPresent(String.self, forKey: .title); url = try? c.decodeIfPresent(String.self, forKey: .url)
            blobId = try? c.decodeIfPresent(String.self, forKey: .blobId); name = try? c.decodeIfPresent(String.self, forKey: .name)
            size = try? c.decodeIfPresent(Int.self, forKey: .size); at = try? c.decodeIfPresent(String.self, forKey: .at)
        }
        enum CodingKeys: String, CodingKey { case kind, title, url, blobId, name, size, at }
    }
    struct Line: Codable, Sendable, Equatable, Identifiable {
        var at: String? = nil
        var by: String? = nil      // who (a name)
        var role: String? = nil    // agent | person
        var text: String
        var id: String { (at ?? "") + "|" + (by ?? "") + "|" + text }
        init(at: String? = nil, by: String? = nil, role: String? = nil, text: String) { self.at = at; self.by = by; self.role = role; self.text = text }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            at = try? c.decodeIfPresent(String.self, forKey: .at)
            let who = try? c.decodeIfPresent(String.self, forKey: .who), b = try? c.decodeIfPresent(String.self, forKey: .by)
            by = who ?? b; role = try? c.decodeIfPresent(String.self, forKey: .role)
            text = try c.decode(String.self, forKey: .text)
        }
        enum CodingKeys: String, CodingKey { case at, by, who, role, text }
        func encode(to e: Encoder) throws {
            var c = e.container(keyedBy: CodingKeys.self)
            try c.encodeIfPresent(at, forKey: .at); try c.encodeIfPresent(by, forKey: .who); try c.encodeIfPresent(role, forKey: .role); try c.encode(text, forKey: .text)
        }
    }
    var title: String? = nil
    var status: String? = nil
    var agent: String? = nil
    var summary: String? = nil
    var checklist: [Task] = []
    var done: Int? = nil
    var total: Int? = nil
    var running: Bool? = nil
    var attachments: [Attachment] = []
    var historyTail: [Line] = []

    init(title: String? = nil, status: String? = nil, agent: String? = nil, summary: String? = nil, checklist: [Task] = [],
         running: Bool? = nil, attachments: [Attachment] = [], historyTail: [Line] = []) {
        self.title = title; self.status = status; self.agent = agent; self.summary = summary; self.checklist = checklist
        self.done = checklist.filter(\.done).count; self.total = checklist.count
        self.running = running; self.attachments = attachments; self.historyTail = historyTail
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        title = try? c.decodeIfPresent(String.self, forKey: .title)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
        agent = try? c.decodeIfPresent(String.self, forKey: .agent)
        summary = try? c.decodeIfPresent(String.self, forKey: .summary)
        checklist = (try? c.decodeIfPresent([Task].self, forKey: .checklist)) ?? []
        done = try? c.decodeIfPresent(Int.self, forKey: .done)
        total = try? c.decodeIfPresent(Int.self, forKey: .total)
        running = try? c.decodeIfPresent(Bool.self, forKey: .running)
        attachments = (try? c.decodeIfPresent([Attachment].self, forKey: .attachments)) ?? []
        historyTail = (try? c.decodeIfPresent([Line].self, forKey: .historyTail)) ?? []
    }
    enum CodingKeys: String, CodingKey { case title, status, agent, summary, checklist, done, total, running, attachments, historyTail }
    var doneCount: Int { done ?? checklist.filter(\.done).count }
    var totalCount: Int { total ?? checklist.count }
}

struct IdResponse: Decodable, Sendable { let id: String }

/// Stored in the Keychain: the one thing the app remembers.
struct Credentials: Codable, Sendable, Equatable {
    let relay: URL
    let phoneId: String
    let token: String
    let phoneName: String
}

enum JSONCoding {
    static let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }()
    static let encoder: JSONEncoder = {
        let e = JSONEncoder(); e.keyEncodingStrategy = .convertToSnakeCase; return e
    }()
}

/// Human wording for "last seen".
func lastSeenText(_ iso: String?, online: Bool, now: Date = Date()) -> String {
    if online { return "Online" }
    guard let iso, let date = ISO8601DateFormatter().date(from: iso) else { return "Asleep. Questions arrive when it wakes up." }
    let f = RelativeDateTimeFormatter(); f.unitsStyle = .full
    return "Asleep, last seen " + f.localizedString(for: date, relativeTo: now)
}

/// `POST /v1/phone/transcribe` answer.
struct Transcript: Decodable, Equatable, Sendable {
    let text: String
    let language: String?
    let duration: Double?
}
