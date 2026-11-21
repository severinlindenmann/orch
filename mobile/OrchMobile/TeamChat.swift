import Foundation

/// Team chat step 2 in the app (ORCH-1175): who is in a ticket chat, who added them, and which workspaces can be added.
/// The members come from the ticket's group (chat groups v2: the host copies `added_by`, `joined_at` and the versions
/// into `group.members` on every copy it sends the phones). Pure and unit-tested.
enum TeamChatRules {
    /// The one line under "Add" before the person picks a workspace (design note step 2, after the challenge).
    static let shareNotice = "They see this ticket and the whole chat."
    static let removeNotice = "If you remove them later, what they already got stays with them."
    /// An older relay dropped the choice (no `team: true` in the reply): the text arrived, nothing was added.
    static let notReady = "Adding from the phone is not ready yet. Add it on the computer."
    static let olderOrch = "older orch"

    static func groupId(ticket: String) -> String { "grp_" + ticket }

    /// The ticket's group, held by the ticket's workspace (`grp_<ticket>`, key = host + id).
    static func group(in groups: [PhoneGroup], workspace: String, ticket: String) -> PhoneGroup? {
        groups.first { $0.key.host == workspace && $0.key.id == groupId(ticket: ticket) }
    }

    /// Everyone in the chat, the ticket's workspace first. Without a group: only the ticket's workspace.
    static func members(_ group: PhoneGroup?, workspace: String, workspaceName: String) -> [GroupMember] {
        guard let group, !group.closed else { return [GroupMember(ws: workspace, name: workspaceName)] }
        let host = group.members.first { $0.ws == workspace } ?? GroupMember(ws: workspace, name: workspaceName)
        return [host] + group.members.filter { $0.ws != workspace }
    }

    /// The person's own workspaces (on this phone) that are not in the chat yet.
    static func candidates(_ workspaces: [Workspace], members: [GroupMember]) -> [Workspace] {
        let inside = Set(members.map(\.ws))
        return workspaces.filter { !inside.contains($0.id) }
    }

    /// "Added by you · 21 Nov" or "Added by Pilatus · 21 Nov"; the ticket's workspace: "This ticket's workspace".
    static func addedLine(_ member: GroupMember, host: String, hostName: String) -> String {
        if member.ws == host { return "This ticket's workspace" }
        var who: String? = nil
        if member.addedBy == "you" { who = "you" } else if member.addedBy == host { who = hostName }
        let day = member.joinedAt.flatMap(dayText)
        switch (who, day) {
        case let (w?, d?): return "Added by \(w) · \(d)"
        case let (w?, nil): return "Added by \(w)"
        case let (nil, d?): return "Added \(d)"
        default: return "In this chat"
        }
    }

    /// Marked "older orch" only when the ticket's workspace speaks chat groups version 2 (it then copies every
    /// member's version) and this member reported none or version 1: its helper does not get @ routing.
    static func isOlder(_ member: GroupMember, members: [GroupMember], host: String) -> Bool {
        guard member.ws != host, let h = members.first(where: { $0.ws == host }), (h.chatGroups ?? 1) >= 2 else { return false }
        return (member.chatGroups ?? 1) < 2
    }

    /// The line on the strip above the chat: "Pilatus, Sales and Bank" (up to three names, then "and 2 more").
    static func stripText(_ members: [GroupMember]) -> String {
        let names = members.map(\.name)
        switch names.count {
        case 0: return ""
        case 1: return names[0]
        case 2, 3: return names.dropLast().joined(separator: ", ") + " and " + names.last!
        default: return names.prefix(2).joined(separator: ", ") + " and \(names.count - 2) more"
        }
    }

    /// The text the person's Add sends with the choice; it stays in the chat as their line.
    static func addText(_ name: String) -> String { "Add \(name) to this chat" }

    /// How long an Add shows "Adding…" before the workspace can be picked again (it was refused or did not arrive;
    /// a refusal is said in the chat).
    static let askWindow: TimeInterval = 120

    /// Waiting rows: workspaces the person asked to add in the last `askWindow` that are not members yet.
    static func pending(_ asked: [String: Date], members: [GroupMember], now: Date = Date()) -> Set<String> {
        Set(asked.filter { now.timeIntervalSince($0.value) < askWindow }.keys).subtracting(members.map(\.ws))
    }

    private static func dayText(_ iso: String) -> String? {
        guard let d = ConversationRules.date(iso) else { return nil }
        return SharedISO.formatter("d MMM").string(from: d)
    }
}
