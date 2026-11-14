import Foundation
import Observation

/// Phone-local "Hide" for a question on Chats ("Needs your OK"). Nothing is sent: the question stays open on the
/// workspace. Rule: a question stays hidden until its conversation gets something newer ("comes back when the helper
/// writes again"). Stored as [questionId: mark ISO string]. The mark is the newest server time in the conversation when
/// the person hid it (not the phone clock), so a phone clock that runs ahead or behind cannot hide or reveal it wrongly.
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
        // Sign-out and `-resetState`: nothing phone-local may stay for the next person (AppModel.reset posts this).
        nonisolated(unsafe) weak var store = self   // only touched on the main queue (queue: .main)
        NotificationCenter.default.addObserver(forName: .orchPhoneReset, object: nil, queue: .main) { _ in store?.clear() }
    }

    func clear() {
        entries = [:]
        defaults.removeObject(forKey: key)
    }

    /// `date`: the newest activity time of the question's conversation (server clock), see `mark(for:activity:)`.
    func hide(_ id: String, at date: Date) {
        entries[id] = formatter.string(from: date)
        save()
    }

    func show(_ id: String) {
        guard entries.removeValue(forKey: id) != nil else { return }
        save()
    }

    func hiddenAt(_ id: String) -> Date? { entries[id].flatMap { formatter.date(from: $0) } }

    /// The hide mark for a question: the newest activity in its conversation, else the question's own time (server clock).
    static func mark(for question: Question, activity: [String: Date]) -> Date {
        activity[key(question)] ?? parse(question.message.createdAt) ?? Date()
    }
    static func key(_ question: Question) -> String { question.message.from + "|" + (question.message.ticket ?? "") }
    nonisolated(unsafe) private static let iso = ISO8601DateFormatter()   // ISO8601DateFormatter is thread-safe
    nonisolated(unsafe) private static let isoFraction: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions.insert(.withFractionalSeconds); return f }()
    static func parse(_ s: String) -> Date? { iso.date(from: s) ?? isoFraction.date(from: s) }

    /// Hidden while the hide mark is not older than the newest thing in the conversation.
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
        return newest.compactMapValues { parse($0) }
    }

    private func save() { defaults.set(entries, forKey: key) }
}

extension Notification.Name {
    /// Posted by AppModel.reset (sign-out, `-resetState`): phone-local stores clear themselves.
    static let orchPhoneReset = Notification.Name("orchPhoneReset")
}
