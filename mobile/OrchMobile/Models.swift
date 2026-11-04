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

/// Workspace names are shown as people would write them: a slug like "e2e-mob-pilatus" becomes "Pilatus".
func displayName(_ raw: String) -> String {
    let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty, !trimmed.contains(" "), trimmed.contains(where: { $0 == "-" || $0 == "_" }) || trimmed == trimmed.lowercased()
    else { return trimmed }
    var words = trimmed.split(whereSeparator: { $0 == "-" || $0 == "_" }).map(String.init)
    let noise: Set<String> = ["e2e", "mob", "test", "dev"]
    let kept = words.filter { !noise.contains($0.lowercased()) }
    if !kept.isEmpty { words = kept }
    return words.map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
}

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
}

struct Question: Codable, Sendable, Equatable, Identifiable {
    let message: QuestionMessage
    let workspaceName: String
    var id: String { message.id }
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
