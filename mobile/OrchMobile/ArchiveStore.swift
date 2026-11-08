import Foundation

/// Phone-local archive, delete and auto-archive of chats (PLAN-A section 2). Nothing here reaches the relay or the workspace.
/// A chat key is `ReadState.key(id)`. Every stamp is the chat's latest item/update time (`lastAt`) when the person acted, so newer
/// activity brings an archived chat back without any event handling: a chat is archived only while its latest activity is not newer
/// than the stamp.
struct ArchiveStore: Codable, Equatable, Sendable {
    /// Archived by hand: key -> latest item/update time at that moment.
    var manual: [String: String] = [:]
    /// Moved back by hand: auto-archive leaves the chat alone until a newer message arrives.
    var kept: [String: String] = [:]
    /// "Delete" on this phone: messages up to this time are hidden.
    var erased: [String: String] = [:]
    /// Auto-archive after N days (3, 7, 14, 30); 0 = off.
    var autoDays = 0

    static let dayChoices = [3, 7, 14, 30]
    static let defaultsKey = "chatArchive"

    static func load(_ defaults: UserDefaults = .standard) -> ArchiveStore {
        defaults.data(forKey: defaultsKey).flatMap { try? JSONDecoder().decode(ArchiveStore.self, from: $0) } ?? ArchiveStore()
    }
    func save(_ defaults: UserDefaults = .standard) {
        if let data = try? JSONEncoder().encode(self) { defaults.set(data, forKey: Self.defaultsKey) }
    }

    /// `status` is nil for General (never archived automatically). `muted`: a muted workspace's archived chat stays archived.
    func isArchived(key: String, status: TopicStatus?, lastAt: String?, muted: Bool, now: Date = Date()) -> Bool {
        let last = lastAt ?? ""
        if let stamp = manual[key], muted || stamp >= last { return true }
        guard autoDays > 0, status == .done, let date = ShellTime.date(lastAt) else { return false }
        if let stamp = kept[key], stamp >= last { return false }
        return now.timeIntervalSince(date) >= Double(autoDays) * 86_400
    }

    mutating func archive(_ key: String, lastAt: String?) { manual[key] = lastAt ?? ""; kept[key] = nil }
    mutating func moveBack(_ key: String, lastAt: String?) { manual[key] = nil; kept[key] = lastAt ?? "" }
    mutating func erase(_ key: String, upTo at: String) { erased[key] = at; manual[key] = nil; kept[key] = nil }
    func erasedUpTo(_ key: String) -> String? { erased[key] }

    /// Delete is offered for General and for finished ticket chats only (an open ticket's chat is derived from the ticket and would reappear).
    static func canDelete(_ status: TopicStatus?) -> Bool {
        guard let status else { return true }
        return status == .done || status == .dropped || status == .stopped || status == .didntWork
    }
}

/// One archived chat in the "Archived" list.
struct ArchivedChat: Identifiable, Equatable, Sendable {
    let id: ConversationID
    let workspaceId: String
    let title: String
    let status: TopicStatus?
    let lastAt: String?
    let byHand: Bool
    var isGeneral: Bool { status == nil }
}

extension ArchiveStore {
    /// Splits one workspace into what the list shows and what is archived. General is hidden when archived.
    func split(_ summary: WorkspaceSummary, now: Date = Date()) -> (topics: [TopicSummary], general: Bool, archived: [ArchivedChat]) {
        let muted = summary.isMuted, ws = summary.id
        var shown: [TopicSummary] = [], archived: [ArchivedChat] = []
        for topic in summary.topics {
            // A topic the workspace has not acked yet cannot be archived.
            let key = ReadState.key(topic.id)
            if !topic.isStarting, isArchived(key: key, status: topic.status, lastAt: topic.lastAt, muted: muted, now: now) {
                archived.append(ArchivedChat(id: topic.id, workspaceId: ws, title: [topic.key, topic.title].compactMap { $0 }.joined(separator: " · "),
                                             status: topic.status, lastAt: topic.lastAt, byHand: manual[key] != nil))
            } else { shown.append(topic) }
        }
        let gKey = ReadState.key(summary.general.id)
        let generalArchived = isArchived(key: gKey, status: nil, lastAt: summary.general.lastAt, muted: muted, now: now)
        if generalArchived {
            archived.append(ArchivedChat(id: summary.general.id, workspaceId: ws, title: "Chat", status: nil, lastAt: summary.general.lastAt, byHand: true))
        }
        return (shown, !generalArchived, archived.sorted { ($0.lastAt ?? "") > ($1.lastAt ?? "") })
    }
}
