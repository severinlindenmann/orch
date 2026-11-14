import Foundation
import Observation

/// Phone-local "Hide" for a question on Chats ("Needs your OK"). Nothing is sent: the question stays open on the
/// workspace. Rule: a question stays hidden until its conversation gets something newer ("comes back when the helper
/// writes again"). Stored as [questionId: hiddenAt ISO string].
@Observable
final class HiddenQuestions {
    static let defaultsKey = "hiddenQuestions"
    private(set) var entries: [String: String]
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let key: String
    @ObservationIgnored private let formatter = ISO8601DateFormatter()

    init(defaults: UserDefaults = .standard, key: String = HiddenQuestions.defaultsKey) {
        self.defaults = defaults
        self.key = key
        self.entries = defaults.dictionary(forKey: key) as? [String: String] ?? [:]
    }

    func hide(_ id: String, at date: Date = Date()) {
        entries[id] = formatter.string(from: date)
        save()
    }

    func show(_ id: String) {
        guard entries.removeValue(forKey: id) != nil else { return }
        save()
    }

    func hiddenAt(_ id: String) -> Date? { entries[id].flatMap { formatter.date(from: $0) } }

    /// Hidden while the hide time is not older than the newest thing in the conversation.
    func isHidden(_ id: String, newestActivity: Date?) -> Bool {
        guard let at = hiddenAt(id) else { return false }
        guard let newest = newestActivity else { return true }
        return at >= newest
    }

    /// Newest time (from the helper, or a question) per "workspace|ticket" for the given questions.
    static func newestActivity(for questions: [Question], messages: [PhoneMessage], allQuestions: [Question]) -> [String: Date] {
        func conv(_ workspace: String, _ ticket: String?) -> String { workspace + "|" + (ticket ?? "") }
        let wanted = Set(questions.map { conv($0.message.from, $0.message.ticket) })
        var newest: [String: String] = [:]
        func note(_ k: String, _ at: String) { if wanted.contains(k), (newest[k] ?? "") < at { newest[k] = at } }
        for m in messages where !m.fromPhone { note(conv(m.workspaceId, m.message.ticket), m.message.createdAt) }
        for q in allQuestions { note(conv(q.message.from, q.message.ticket), q.message.createdAt) }
        let parse = ISO8601DateFormatter()
        let fractional = ISO8601DateFormatter(); fractional.formatOptions.insert(.withFractionalSeconds)
        return newest.compactMapValues { parse.date(from: $0) ?? fractional.date(from: $0) }
    }

    private func save() { defaults.set(entries, forKey: key) }
}
