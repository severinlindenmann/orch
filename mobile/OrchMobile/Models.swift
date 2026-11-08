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

/// `{on, since, ends_at, machine}`: the computer keeps awake and sends every question to this phone.
struct MobileMode: Codable, Sendable, Equatable {
    let on: Bool
    var since: String? = nil
    var endsAt: String? = nil
    var machine: String? = nil
}

struct Workspace: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let name: String
    let description: String?
    let tags: [String]
    let online: Bool
    let lastSeen: String?
    let openQuestions: Int
    /// `null`, a UTC time, or "forever" (PATCH /v1/phone/workspaces/<id>).
    var mutedUntil: String? = nil
    /// Mobile mode of the workspace's computer (relay-api.md, Mobile mode); nil from an older relay.
    var mobileMode: MobileMode? = nil
    /// Look chosen in the workspace (contracts/look.md); nil = letter + Automatic colour. Unknown values fall back in `Look.shown`.
    var icon: String? = nil
    var color: String? = nil
    var displayName: String { OrchMobile.displayName(name) }
    func isMuted(now: Date = Date()) -> Bool {
        guard let m = mutedUntil else { return false }
        if m == "forever" { return true }
        return (ISO8601DateFormatter().date(from: m)).map { $0 > now } ?? false
    }
    /// Online while the last call is at most 5 minutes old (Presence.swift).
    func presence(now: Date = Date()) -> Presence { Presence.of(lastSeen: lastSeen, now: now) }
}

struct QuestionBody: Codable, Sendable, Equatable {
    let questionId: String
    let title: String?
    let text: String
    let options: [String]
    let recommended: String?
    /// option -> ticket_view attachment id shown next to it (A/B choices, approve with a preview).
    var previews: [String: String]? = nil
    /// Permission questions: what "Always" covers, shown as "Always allow <scope>".
    var scope: String? = nil
    var allowQuestion: Bool? = nil // allow_question via JSONCoding
    var groupRef: GroupRef? = nil // group_ref via JSONCoding
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

enum AnswerWord: String, Equatable {
    case once, always, no

    static func parse(_ value: String) -> AnswerWord? {
        if let wire = AnswerWord(rawValue: value) { return wire }
        let old = value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").lowercased()
        switch old {
        case "allow once": return .once
        case "always": return .always
        case "ignore", "no": return .no
        default: return nil
        }
    }
    var allowMode: String? { self == .no ? nil : self == .always ? "permanent" : "once" }
    /// approved events use once|always, while allow messages use once|permanent.
    var approvedMode: String? { self == .no ? nil : rawValue }
}

struct Question: Codable, Sendable, Equatable, Identifiable {
    let message: QuestionMessage
    let workspaceName: String
    var id: String { message.id }
    /// Compatibility for existing Chat cards; group cards must use isGroupAllow.
    var isLegacyAllow: Bool {
        guard message.body.allowQuestion == nil else { return false }
        let options = message.body.options.map { $0.lowercased() }
        return (options.contains("once") || options.contains("allow once")) && options.contains("always")
    }
    var isGroupAllow: Bool {
        message.body.allowQuestion == true && message.body.options.count == 3 &&
            Set(message.body.options) == Set(["once", "always", "no"])
    }
    var isAllow: Bool { isGroupAllow || isLegacyAllow }
    /// Labels never change the raw option sent to the relay.
    func label(_ option: String) -> String {
        guard isAllow else { return option }
        if option == "Once" { return "Allow once" } // Existing Chat option.
        switch AnswerWord.parse(option) {
        case .once: return "Allow once"
        case .always: return message.body.scope.map { "Always allow \($0)" } ?? "Always"
        case .no: return "No"
        case nil: return option
        }
    }
    /// The attachment id previewed next to an option, if any.
    func previewId(for option: String) -> String? { message.body.previews?[option] }
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

/// `GET /v1/phone/messages`: a text between this phone and a workspace (either direction). contracts/message.schema.json, `text`.
struct TextBody: Codable, Sendable, Equatable {
    /// Empty when the text only carries attachments, a voice memo, a location or feedback.
    var text: String = ""
    /// Work update about the message's ticket; nil on a plain text.
    var update: TextUpdate? = nil
    /// Set on the phone's own texts (the UUID of the outbox item).
    var clientId: String? = nil
    var general: Bool? = nil
    // Incoming Chat metadata; never included in a phone send.
    var by: String? = nil
    var via: String? = nil
    var phone: String? = nil
    var day: String? = nil
    /// Workspace texts worth hearing (GET /v1/phone/speech/<id>).
    var speak: SpeakHint? = nil
    var attachments: [MessageAttachment] = []
    var voice: VoiceMemo? = nil
    var location: LocationShare? = nil
    var feedback: Feedback? = nil
    var ticketView: TicketSnapshot? = nil
    var group: GroupInfo? = nil
    var groupEvent: GroupEvent? = nil
    var origin: GroupOrigin? = nil
    var echoOf: String? = nil
    var toPerson: Bool? = nil
    var task: GroupTask? = nil
    var sharedFiles: [String]? = nil

    init(text: String = "", update: TextUpdate? = nil, clientId: String? = nil, general: Bool? = nil, speak: SpeakHint? = nil,
         attachments: [MessageAttachment] = [], voice: VoiceMemo? = nil, location: LocationShare? = nil, feedback: Feedback? = nil,
         ticketView: TicketSnapshot? = nil,
         group: GroupInfo? = nil, groupEvent: GroupEvent? = nil, by: String? = nil, via: String? = nil, phone: String? = nil,
         origin: GroupOrigin? = nil, echoOf: String? = nil, toPerson: Bool? = nil, task: GroupTask? = nil, sharedFiles: [String]? = nil) {
        self.text = text; self.update = update; self.clientId = clientId; self.general = general; self.speak = speak
        self.attachments = attachments; self.voice = voice; self.location = location; self.feedback = feedback; self.ticketView = ticketView
        self.group = group; self.groupEvent = groupEvent; self.by = by; self.via = via; self.phone = phone
        self.origin = origin; self.echoOf = echoOf; self.toPerson = toPerson; self.task = task; self.sharedFiles = sharedFiles
    }
    private enum CodingKeys: String, CodingKey {
        case text, update, clientId, general, speak, attachments, voice, location, feedback, ticketView
        case group, groupEvent, by, via, phone, day, origin, echoOf, toPerson, task, sharedFiles
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        text = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? ""
        update = try? c.decodeIfPresent(TextUpdate.self, forKey: .update)
        clientId = try? c.decodeIfPresent(String.self, forKey: .clientId)
        general = try? c.decodeIfPresent(Bool.self, forKey: .general)
        by = try? c.decodeIfPresent(String.self, forKey: .by)
        via = try? c.decodeIfPresent(String.self, forKey: .via)
        phone = try? c.decodeIfPresent(String.self, forKey: .phone)
        day = try? c.decodeIfPresent(String.self, forKey: .day)
        speak = try? c.decodeIfPresent(SpeakHint.self, forKey: .speak)
        attachments = (try? c.decodeIfPresent([MessageAttachment].self, forKey: .attachments)) ?? []
        voice = try? c.decodeIfPresent(VoiceMemo.self, forKey: .voice)
        location = try? c.decodeIfPresent(LocationShare.self, forKey: .location)
        feedback = try? c.decodeIfPresent(Feedback.self, forKey: .feedback)
        ticketView = try? c.decodeIfPresent(TicketSnapshot.self, forKey: .ticketView)
        group = try? c.decodeIfPresent(GroupInfo.self, forKey: .group)
        groupEvent = try? c.decodeIfPresent(GroupEvent.self, forKey: .groupEvent)
        origin = try? c.decodeIfPresent(GroupOrigin.self, forKey: .origin)
        echoOf = try? c.decodeIfPresent(String.self, forKey: .echoOf)
        toPerson = try? c.decodeIfPresent(Bool.self, forKey: .toPerson)
        task = try? c.decodeIfPresent(GroupTask.self, forKey: .task)
        sharedFiles = try? c.decodeIfPresent([String].self, forKey: .sharedFiles)
    }
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: CodingKeys.self)
        if !text.isEmpty { try c.encode(text, forKey: .text) }
        try c.encodeIfPresent(update, forKey: .update); try c.encodeIfPresent(clientId, forKey: .clientId)
        try c.encodeIfPresent(general, forKey: .general); try c.encodeIfPresent(speak, forKey: .speak)
        if !attachments.isEmpty { try c.encode(attachments, forKey: .attachments) }
        try c.encodeIfPresent(voice, forKey: .voice); try c.encodeIfPresent(location, forKey: .location)
        try c.encodeIfPresent(feedback, forKey: .feedback); try c.encodeIfPresent(ticketView, forKey: .ticketView)
    }
}
struct TextUpdate: Codable, Sendable, Equatable { let kind: String; var title: String? = nil }
struct SpeakHint: Codable, Sendable, Equatable { let lang: String; var summary: String? = nil }

/// A phone upload sent with a text (`body.attachments[]`).
struct MessageAttachment: Codable, Sendable, Equatable, Identifiable {
    enum Kind: String, Codable, Sendable { case image, file, voice }
    let blobId: String
    let kind: Kind
    let name: String
    let size: Int
    let mime: String
    var duration: Double? = nil
    var id: String { blobId }
}
/// `body.voice`: the recording and what was said.
struct VoiceMemo: Codable, Sendable, Equatable {
    enum LangSource: String, Codable, Sendable { case detected, setting, corrected }
    let blobId: String
    let transcript: String
    let lang: String
    let langSource: LangSource
}
struct LocationShare: Codable, Sendable, Equatable {
    let lat: Double
    let lon: Double
    var label: String? = nil
    var accuracyM: Double? = nil
}
/// Feedback on one artifact revision (`body.feedback`). Never an approval to publish.
struct Feedback: Codable, Sendable, Equatable {
    enum Verdict: String, Codable, Sendable { case approve, changes }
    let artifactId: String
    let artifactRev: String
    let verdict: Verdict
    var pins: [Pin] = []
}
struct Pin: Codable, Sendable, Equatable {
    let n: Int
    let anchor: Anchor
    var text: String? = nil
    var voiceBlobId: String? = nil
    var transcript: String? = nil
}
/// Where a pin sits: html {selector and/or quote, offset, viewportW}, pdf {page, x, y}, image {x, y}; x/y are fractions 0..1.
struct Anchor: Codable, Sendable, Equatable {
    enum Kind: String, Codable, Sendable { case html, pdf, image }
    let type: Kind
    var selector: String? = nil
    var quote: String? = nil
    var offset: Int? = nil
    var viewportW: Int? = nil
    var page: Int? = nil
    var x: Double? = nil
    var y: Double? = nil
}

struct TextMessage: Codable, Sendable, Equatable {
    let id: String
    let from: String
    let to: String
    let type: String
    let createdAt: String
    let ticket: String?
    let body: TextBody
    var key: String? = nil
    /// The text this one answers or acknowledges (an ack/working update names the phone text it started).
    var replyTo: String? = nil
}
struct PhoneMessage: Codable, Sendable, Equatable, Identifiable {
    let message: TextMessage
    let workspaceName: String
    /// Phone texts: when the receiving workspace acked it (the second tick). Null on workspace texts.
    var deliveredAt: String? = nil
    /// Phone texts: `body.client_id`.
    var clientId: String? = nil
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
        /// Links only (from the workspace's link module): what the link is ("GitHub · Pull request"), the site or
        /// link-type icon key, the tile letters and the add-on's status. Older workspaces send none of them.
        var linkType: String? = nil
        var icon: String? = nil
        var mono: String? = nil
        var status: String? = nil
        /// Stable per artifact across revisions (`a_` + 12 hex), and this revision. Optional for older workspaces; feedback needs both.
        var artifactId: String? = nil
        var rev: String? = nil
        /// image | file are blobs; link | html | pr | commit are addresses.
        var isBlob: Bool { kind == "image" || kind == "file" }
        var id: String { artifactId ?? [kind, blobId ?? url ?? name ?? title ?? "", at ?? ""].joined(separator: "|") }
        /// What a person reads: the proof title, else the file name.
        var label: String? { title ?? name }
        init(kind: String = "file", title: String? = nil, url: String? = nil, blobId: String? = nil, name: String? = nil, size: Int? = nil, at: String? = nil,
             linkType: String? = nil, icon: String? = nil, mono: String? = nil, status: String? = nil, artifactId: String? = nil, rev: String? = nil) {
            self.artifactId = artifactId; self.rev = rev
            self.kind = kind; self.title = title; self.url = url; self.blobId = blobId; self.name = name; self.size = size; self.at = at
            self.linkType = linkType; self.icon = icon; self.mono = mono; self.status = status
        }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "file"
            title = try? c.decodeIfPresent(String.self, forKey: .title); url = try? c.decodeIfPresent(String.self, forKey: .url)
            blobId = try? c.decodeIfPresent(String.self, forKey: .blobId); name = try? c.decodeIfPresent(String.self, forKey: .name)
            size = try? c.decodeIfPresent(Int.self, forKey: .size); at = try? c.decodeIfPresent(String.self, forKey: .at)
            linkType = try? c.decodeIfPresent(String.self, forKey: .linkType); icon = try? c.decodeIfPresent(String.self, forKey: .icon)
            mono = try? c.decodeIfPresent(String.self, forKey: .mono); status = try? c.decodeIfPresent(String.self, forKey: .status)
            artifactId = try? c.decodeIfPresent(String.self, forKey: .artifactId); rev = try? c.decodeIfPresent(String.self, forKey: .rev)
        }
        enum CodingKeys: String, CodingKey { case kind, title, url, blobId, name, size, at, linkType = "label", icon, mono, status, artifactId = "id", rev }
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
    var started: Bool? = nil
    var attachments: [Attachment] = []
    var historyTail: [Line] = []
    /// What the ticket points at (web addresses, other tickets, files it produced, project files). Unknown kinds are left out.
    var refs: [TicketRef] = []

    init(title: String? = nil, status: String? = nil, agent: String? = nil, summary: String? = nil, checklist: [Task] = [],
         running: Bool? = nil, started: Bool? = nil, attachments: [Attachment] = [], historyTail: [Line] = [], refs: [TicketRef] = []) {
        self.refs = refs
        self.title = title; self.status = status; self.agent = agent; self.summary = summary; self.checklist = checklist
        self.done = checklist.filter(\.done).count; self.total = checklist.count
        self.running = running; self.started = started; self.attachments = attachments; self.historyTail = historyTail
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
        started = try? c.decodeIfPresent(Bool.self, forKey: .started)
        attachments = (try? c.decodeIfPresent([Attachment].self, forKey: .attachments)) ?? []
        historyTail = (try? c.decodeIfPresent([Line].self, forKey: .historyTail)) ?? []
        refs = TicketRef.decodeList(c, forKey: .refs)
    }
    enum CodingKeys: String, CodingKey { case title, status, agent, summary, checklist, done, total, running, started, attachments, historyTail, refs }
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

/// `GET/PATCH /v1/phone/settings`.
struct PhoneSettings: Codable, Sendable, Equatable {
    enum Speak: String, Codable, Sendable, CaseIterable { case auto, always, never }
    var speak: Speak = .auto
    var swissGerman: Bool = false
    var ttsCapUsd: Double = 10
    var ttsUsedUsdMonth: Double = 0
    /// Read-aloud budget left this month (never below 0).
    var ttsLeftUsd: Double { max(0, ttsCapUsd - ttsUsedUsdMonth) }
}
/// Body of `PATCH /v1/phone/settings`: at least one field.
struct SettingsPatch: Codable, Sendable, Equatable {
    var speak: PhoneSettings.Speak? = nil
    var swissGerman: Bool? = nil
    var ttsCapUsd: Double? = nil
    var isValid: Bool { (speak != nil || swissGerman != nil || ttsCapUsd != nil) && (ttsCapUsd.map { $0 >= 0 && $0 <= 100 } ?? true) }
}
/// `POST /v1/phone/blobs`.
struct BlobUpload: Codable, Sendable, Equatable { let blobId: String; let size: Int; let sha256: String }
/// `POST /v1/phone/send` and `/answer`: `duplicate` is true when the relay already had this client_id.
struct SendReceipt: Codable, Sendable, Equatable { let id: String; var clientId: String? = nil; var duplicate: Bool? = nil }
/// `POST /v1/phone/invitations/redeem`.
struct RedeemResponse: Codable, Sendable, Equatable { let workspaces: [WorkspaceRef] }

/// Body of `PATCH /v1/phone/workspaces/<ws>`: `muted_until` is always sent (null = unmute).
enum Mute: Equatable, Sendable {
    case off, forever, until(Date)
    var wire: String? {
        switch self {
        case .off: nil
        case .forever: "forever"
        case .until(let d): ISO8601DateFormatter().string(from: d)
        }
    }
}

/// `POST /v1/phone/send` (phone-api.schema.json, send_request). Built by the Outbox from a draft; `validate()` mirrors the relay's 422 rules.
struct SendRequest: Codable, Sendable, Equatable {
    let to: String
    let clientId: String
    var text: String? = nil
    var ticket: String? = nil
    var general: Bool? = nil
    var replyTo: String? = nil
    var attachments: [MessageAttachment]? = nil
    var voice: VoiceMemo? = nil
    var location: LocationShare? = nil
    var feedback: Feedback? = nil

    enum Problem: Error, Equatable { case nothingToSend, badTarget, badLocation, generalWithTicket, feedbackNeedsTicket, badClientId, tooManyAttachments, attachmentTooBig, badFeedback }
    static let maxBlobBytes = 25 * 1024 * 1024
    static func isClientId(_ s: String) -> Bool { s.range(of: "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", options: .regularExpression) != nil }

    func validate() throws {
        guard Self.isClientId(clientId) else { throw Problem.badClientId }
        guard to.range(of: "^ws_[a-z0-9]{10}$", options: .regularExpression) != nil else { throw Problem.badTarget }
        if let l = location, !(-90...90).contains(l.lat) || !(-180...180).contains(l.lon) { throw Problem.badLocation }
        guard (text?.isEmpty == false) || !(attachments ?? []).isEmpty || voice != nil || location != nil || feedback != nil else { throw Problem.nothingToSend }
        if general == true, ticket != nil { throw Problem.generalWithTicket }
        if feedback != nil, ticket == nil { throw Problem.feedbackNeedsTicket }
        if let a = attachments {
            if a.count > 10 { throw Problem.tooManyAttachments }
            if a.contains(where: { $0.size > Self.maxBlobBytes || $0.size < 1 }) { throw Problem.attachmentTooBig }
        }
        if let f = feedback {
            if f.verdict == .changes && f.pins.isEmpty { throw Problem.badFeedback }
            for p in f.pins where (p.text?.isEmpty ?? true) && p.voiceBlobId == nil { throw Problem.badFeedback }
            for p in f.pins {
                let a = p.anchor
                let inRange = [a.x, a.y].allSatisfy { $0.map { $0 >= 0 && $0 <= 1 } ?? true }
                switch a.type {
                case .html: if a.selector == nil && a.quote == nil { throw Problem.badFeedback }
                case .pdf: if a.page == nil || a.x == nil || a.y == nil { throw Problem.badFeedback }
                case .image: if a.x == nil || a.y == nil { throw Problem.badFeedback }
                }
                if !inRange { throw Problem.badFeedback }
            }
        }
    }
}
/// `POST /v1/phone/answer`.
struct AnswerRequest: Codable, Sendable, Equatable { let questionMessageId: String; let answer: String; let clientId: String }
