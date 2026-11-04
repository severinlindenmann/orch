import Foundation

/// Wire models of the phone API (contracts/relay-api.md). Unknown fields are ignored.
struct ListResponse<T: Decodable & Sendable>: Decodable, Sendable {
    let items: [T]
    let next: String?
}

struct WorkspaceRef: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let name: String
}

struct PairResponse: Decodable, Sendable {
    let phoneId: String
    let token: String
    let workspaces: [WorkspaceRef]
}

struct Workspace: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let name: String
    let description: String?
    let tags: [String]
    let online: Bool
    let lastSeen: String?
    let openQuestions: Int
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
    guard let iso, let date = ISO8601DateFormatter().date(from: iso) else { return "Offline" }
    let f = RelativeDateTimeFormatter(); f.unitsStyle = .full
    return "Seen " + f.localizedString(for: date, relativeTo: now)
}
